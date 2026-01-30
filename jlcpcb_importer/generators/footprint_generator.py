"""Generate KiCad .kicad_mod footprint files from EasyEDA shape data.

Uses the vendored KicadModTree library.  Ported from the original
JLC2KiCadLib footprint handlers.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from math import acos, cos, pi, pow, radians, sin, sqrt

from vendor.KicadModTree import (
    Arc,
    Circle,
    Footprint,
    KicadFileHandler,
    Line,
    Model,
    Pad,
    Polygon,
    RectFill,
    RectLine,
    Text,
    Translation,
    Vector2D,
)

from ..api.models import FootprintShapeData
from ..utils.logger import get_logger

log = get_logger()

# ------------------------------------------------------------------
# Layer mapping (EasyEDA layer id → KiCad layer name)
# ------------------------------------------------------------------

_LAYER_MAP: dict[str, str] = {
    "1": "F.Cu", "2": "B.Cu", "3": "F.SilkS", "4": "B.Silks",
    "5": "F.Paste", "6": "B.Paste", "7": "F.Mask", "8": "B.Mask",
    "10": "Edge.Cuts", "11": "", "12": "F.Fab",
    "99": "", "100": "", "101": "",
}


def _mil2mm(value: float | str) -> float:
    return float(value) / 3.937


# ------------------------------------------------------------------
# Footprint bounding-box tracker
# ------------------------------------------------------------------


@dataclass
class _FootprintBounds:
    max_x: float = -10000.0
    max_y: float = -10000.0
    min_x: float = 10000.0
    min_y: float = 10000.0

    def update(self, x: float, y: float) -> None:
        self.max_x = max(self.max_x, x)
        self.min_x = min(self.min_x, x)
        self.max_y = max(self.max_y, y)
        self.min_y = min(self.min_y, y)


# ------------------------------------------------------------------
# Shape handlers
# ------------------------------------------------------------------


def _h_TRACK(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    width = _mil2mm(data[0])
    points = [_mil2mm(p) for p in data[3].split(" ") if p]
    try:
        layer = _LAYER_MAP[data[1]]
    except KeyError:
        log.warning("TRACK: unknown layer %s, using F.SilkS", data[1])
        layer = "F.SilkS"
    if not layer:
        return

    for i in range(len(points) // 2 - 1):
        start = [points[2 * i], points[2 * i + 1]]
        end = [points[2 * i + 2], points[2 * i + 3]]
        bounds.update(start[0], start[1])
        bounds.update(end[0], end[1])
        kicad_mod.append(Line(start=start, end=end, width=width, layer=layer))


def _h_PAD(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    TOPLAYER, BOTTOMLAYER, MULTILAYER = "1", "2", "11"

    shape_type = data[0]
    at = [_mil2mm(data[1]), _mil2mm(data[2])]
    size = [_mil2mm(data[3]), _mil2mm(data[4])]
    layer = data[5]
    pad_number = data[7]
    drill_diameter = float(_mil2mm(data[8])) * 2
    drill_size = drill_diameter
    rotation = float(data[10])
    drill_offset = float(_mil2mm(data[12])) if data[12] else 0
    primitives = ""

    if layer == MULTILAYER:
        pad_type, pad_layer = Pad.TYPE_THT, Pad.LAYERS_THT
    elif layer == TOPLAYER:
        pad_type, pad_layer = Pad.TYPE_SMT, Pad.LAYERS_SMT
    elif layer == BOTTOMLAYER:
        pad_type, pad_layer = Pad.TYPE_SMT, ["B.Cu", "B.Mask", "B.Paste"]
    else:
        log.warning("PAD %s: unknown layer %s, using SMT", pad_number, layer)
        pad_type, pad_layer = Pad.TYPE_SMT, Pad.LAYERS_SMT

    if shape_type == "OVAL":
        shape = Pad.SHAPE_OVAL
        if drill_offset == 0:
            drill_size = drill_diameter
        elif (drill_diameter < drill_offset) ^ (size[0] > size[1]):
            drill_size = [drill_diameter, drill_offset]
        else:
            drill_size = [drill_offset, drill_diameter]
    elif shape_type == "RECT":
        shape = Pad.SHAPE_RECT
        if drill_offset == 0:
            drill_size = drill_diameter
        else:
            drill_size = [drill_diameter, drill_offset]
    elif shape_type == "ELLIPSE":
        shape = Pad.SHAPE_CIRCLE
    elif shape_type == "POLYGON":
        shape = Pad.SHAPE_CUSTOM
        pts = []
        for i, coord in enumerate(data[9].split(" ")):
            pts.append(_mil2mm(coord) - at[i % 2])
        primitives = [Polygon(nodes=zip(pts[::2], pts[1::2], strict=True))]
        size = [0.1, 0.1]
        drill_size = 1 if drill_offset == 0 else [drill_diameter, drill_offset]
    else:
        log.warning("PAD %s: unknown shape '%s', using OVAL", pad_number, shape_type)
        shape = Pad.SHAPE_OVAL

    bounds.update(at[0], at[1])
    kicad_mod.append(Pad(
        number=pad_number, type=pad_type, shape=shape,
        at=at, size=size, rotation=rotation,
        drill=drill_size, layers=pad_layer, primitives=primitives,
    ))


def _h_ARC(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    width_raw = data[0]
    layer = _LAYER_MAP.get(data[1], "F.SilkS")
    if not layer:
        return
    svg_path = data[3]

    pattern = (
        r"M\s*([-\d.]+)[\s,]+([-\d.]+)\s*A\s*([-\d.]+)[\s,]+"
        r"([-\d.]+)[\s,]+([-\d.]+)[\s,]+(\d)[\s,]+(\d)[\s,]+([-\d.]+)[\s,]+([-\d.]+)"
    )
    match = re.search(pattern, svg_path)
    if not match:
        log.warning("ARC: failed to parse SVG path")
        return

    start_x, start_y = float(match.group(1)), float(match.group(2))
    rx, ry = float(match.group(3)), float(match.group(4))
    large_arc_flag = int(match.group(6))
    sweep_flag = int(match.group(7))
    end_x, end_y = float(match.group(8)), float(match.group(9))

    w = _mil2mm(width_raw)
    sx, sy = _mil2mm(start_x), _mil2mm(start_y)
    ex, ey = _mil2mm(end_x), _mil2mm(end_y)
    r_x, r_y = _mil2mm(rx), _mil2mm(ry)

    start, end = [sx, sy], [ex, ey]

    if abs(sx - ex) < 1e-6 and abs(sy - ey) < 1e-6:
        radius = r_x
        center = [sx + radius, sy] if sweep_flag == 1 else [sx - radius, sy]
        kicad_mod.append(Circle(center=center, radius=radius, width=w, layer=layer))
        return

    if sweep_flag == 0:
        start, end = end, start

    mid = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2]
    vec1 = Vector2D(mid[0] - start[0], mid[1] - start[1])
    length_sq = r_x * r_y - pow(vec1.distance_to((0, 0)), 2)
    if length_sq < 0:
        length_sq = 0
        large_arc_flag = 1

    vec2 = vec1.rotate(-90) if large_arc_flag == 1 else vec1.rotate(90)
    mag = sqrt(vec2[0] ** 2 + vec2[1] ** 2)
    if mag == 0:
        return
    vec2 = Vector2D(vec2[0] / mag, vec2[1] / mag)
    cen = Vector2D(mid) + vec2 * sqrt(length_sq)

    kicad_mod.append(Arc(start=start, end=end, width=w, center=cen, layer=layer))


def _h_CIRCLE(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    if data[4] == "100":
        return
    cx, cy = _mil2mm(data[0]), _mil2mm(data[1])
    radius, width = _mil2mm(data[2]), _mil2mm(data[3])
    layer = _LAYER_MAP.get(data[4], "F.SilkS")
    if not layer:
        return
    kicad_mod.append(Circle(center=[cx, cy], radius=radius, width=width, layer=layer))


def _svg_arc_to_points(x1, y1, rx, ry, rotation, large_arc, sweep, x2, y2):
    """Convert an SVG arc to a list of (x, y) points."""
    if x1 == x2 and y1 == y2:
        return []
    if rx == 0 or ry == 0:
        return [(x2, y2)]

    rx, ry = abs(rx), abs(ry)
    cr, sr = cos(radians(rotation)), sin(radians(rotation))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cr * dx + sr * dy
    y1p = -sr * dx + cr * dy

    rx2, ry2 = rx * rx, ry * ry
    x1p2, y1p2 = x1p * x1p, y1p * y1p
    lam = x1p2 / rx2 + y1p2 / ry2
    if lam > 1:
        s = sqrt(lam)
        rx *= s; ry *= s
        rx2, ry2 = rx * rx, ry * ry

    denom = rx2 * y1p2 + ry2 * x1p2
    if denom == 0:
        return [(x2, y2)]

    sign = -1 if large_arc == sweep else 1
    sq = max(0, (rx2 * ry2 - rx2 * y1p2 - ry2 * x1p2) / denom)
    coef = sign * sqrt(sq)
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx

    cx = cr * cxp - sr * cyp + (x1 + x2) / 2
    cy = sr * cxp + cr * cyp + (y1 + y2) / 2

    def _angle(ux, uy, vx, vy):
        n = sqrt(ux * ux + uy * uy) * sqrt(vx * vx + vy * vy)
        if n == 0:
            return 0
        c = max(-1, min(1, (ux * vx + uy * vy) / n))
        a = acos(c)
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry,
        (-x1p - cxp) / rx, (-y1p - cyp) / ry,
    )
    if sweep == 0 and dtheta > 0:
        dtheta -= 2 * pi
    elif sweep == 1 and dtheta < 0:
        dtheta += 2 * pi

    n_seg = max(8, int(abs(dtheta) / (2 * pi) * 32))
    pts = []
    for i in range(1, n_seg + 1):
        a = theta1 + dtheta * i / n_seg
        x = cx + rx * cos(a) * cr - ry * sin(a) * sr
        y = cy + rx * cos(a) * sr + ry * sin(a) * cr
        pts.append((x, y))
    return pts


def _h_SOLIDREGION(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    layer = "Edge.Cuts" if data[3] == "npth" else _LAYER_MAP.get(data[0], "F.SilkS")
    if not layer:
        return

    path = data[2]
    points = []
    cur = (0.0, 0.0)

    cmd_pat = re.compile(r"([MLAZ])\s*((?:[-+]?\d*\.?\d+[\s,]*)*)", re.IGNORECASE)
    num_pat = re.compile(r"[-+]?\d*\.?\d+")

    for m in cmd_pat.finditer(path):
        cmd = m.group(1).upper()
        params = [float(n) for n in num_pat.findall(m.group(2))]

        if cmd == "M" and len(params) >= 2:
            cur = (params[0], params[1])
            points.append(cur)
        elif cmd == "L" and len(params) >= 2:
            cur = (params[0], params[1])
            points.append(cur)
        elif cmd == "A" and len(params) >= 7:
            arc_pts = _svg_arc_to_points(
                cur[0], cur[1],
                params[0], params[1], params[2],
                int(params[3]), int(params[4]),
                params[5], params[6],
            )
            points.extend(arc_pts)
            cur = (params[5], params[6])

    points = [(_mil2mm(p[0]), _mil2mm(p[1])) for p in points]
    if points:
        kicad_mod.append(Polygon(nodes=points, layer=layer))


def _h_SVGNODE(
    data: list[str],
    kicad_mod: Footprint,
    bounds: _FootprintBounds,
    *,
    model_uuids: list[str] | None = None,
) -> None:
    """Parse 3D model metadata – only collects UUIDs, actual download is separate."""
    try:
        parsed = json.loads(data[0])
    except (json.JSONDecodeError, IndexError):
        log.warning("SVGNODE: failed to parse JSON data")
        return

    if model_uuids is not None:
        uuid = parsed.get("attrs", {}).get("uuid", "")
        if uuid:
            model_uuids.append(uuid)


def _h_VIA(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    log.warning("VIA not supported (often for heat dissipation – check datasheet)")


def _h_RECT(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    xs, ys = float(_mil2mm(data[0])), float(_mil2mm(data[1]))
    xd, yd = float(_mil2mm(data[2])), float(_mil2mm(data[3]))
    start, end = [xs, ys], [xs + xd, ys + yd]
    width = _mil2mm(data[7])
    layer = _LAYER_MAP.get(data[4], "F.SilkS")
    if not layer:
        return

    if width == 0:
        kicad_mod.append(RectFill(start=start, end=end, layer=layer))
    else:
        kicad_mod.append(RectLine(start=start, end=end, width=width, layer=layer))


def _h_HOLE(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    d = _mil2mm(data[2]) * 2
    kicad_mod.append(Pad(
        number="", type=Pad.TYPE_NPTH, shape=Pad.SHAPE_CIRCLE,
        at=[_mil2mm(data[0]), _mil2mm(data[1])],
        size=d, rotation=0, drill=d, layers=Pad.LAYERS_NPTH,
    ))


def _h_TEXT(data: list[str], kicad_mod: Footprint, bounds: _FootprintBounds) -> None:
    kicad_mod.append(Text(
        type="user", text=data[9],
        at=[_mil2mm(data[1]), _mil2mm(data[2])], layer="F.SilkS",
    ))


_HANDLERS: dict[str, callable] = {
    "TRACK": _h_TRACK, "PAD": _h_PAD, "ARC": _h_ARC,
    "CIRCLE": _h_CIRCLE, "SOLIDREGION": _h_SOLIDREGION,
    "SVGNODE": _h_SVGNODE, "VIA": _h_VIA, "RECT": _h_RECT,
    "HOLE": _h_HOLE, "TEXT": _h_TEXT,
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def generate_footprint(
    fp_data: FootprintShapeData,
    component_id: str,
    output_dir: str,
    footprint_lib: str,
    model_3d_path: str | None = None,
    model_offset: tuple[float, float, float] = (0, 0, 0),
    model_rotation: tuple[float, float, float] = (0, 0, 0),
) -> str | None:
    """Generate a KiCad .kicad_mod footprint file.

    Args:
        fp_data: Parsed footprint shape data from the API.
        component_id: LCSC part number (used in tags).
        output_dir: Base output directory.
        footprint_lib: Footprint library folder name (``*.pretty``).
        model_3d_path: Optional path to a 3D model file.
        model_offset: 3D model (x, y, z) offset.
        model_rotation: 3D model (rx, ry, rz) rotation.

    Returns:
        The footprint name on success, or None on failure.
    """
    name = fp_data.name or "NoName"
    translation = fp_data.translation
    bounds = _FootprintBounds()

    kicad_mod = Footprint(f'"{name}"')
    kicad_mod.setDescription(f"{name} footprint")
    kicad_mod.setTags(f"{name} footprint {component_id}")

    # Collect model UUIDs for later download
    model_uuids: list[str] = []

    for line in fp_data.shapes:
        args = line.split("~")
        cmd = args[0]
        if cmd not in _HANDLERS:
            log.debug("footprint handler not found: %s", cmd)
            continue
        if cmd == "SVGNODE":
            _h_SVGNODE(args[1:], kicad_mod, bounds, model_uuids=model_uuids)
        else:
            _HANDLERS[cmd](args[1:], kicad_mod, bounds)

    # Set attribute
    is_tht = any(
        isinstance(child, Pad) and child.type == Pad.TYPE_THT
        for child in kicad_mod.getAllChilds()
    )
    kicad_mod.setAttribute("through_hole" if is_tht else "smd")

    # Apply translation
    kicad_mod.insert(Translation(-_mil2mm(translation[0]), -_mil2mm(translation[1])))

    # Adjust bounds
    bounds.max_x -= _mil2mm(translation[0])
    bounds.max_y -= _mil2mm(translation[1])
    bounds.min_x -= _mil2mm(translation[0])
    bounds.min_y -= _mil2mm(translation[1])

    # Reference / value / user text
    cx = (bounds.min_x + bounds.max_x) / 2
    kicad_mod.append(Text(
        type="reference", text="REF**",
        at=[cx, bounds.min_y - 2], layer="F.SilkS",
    ))
    kicad_mod.append(Text(
        type="user", text="${REFERENCE}",
        at=[cx, (bounds.min_y + bounds.max_y) / 2], layer="F.Fab",
    ))
    kicad_mod.append(Text(
        type="value", text=name,
        at=[cx, bounds.max_y + 2], layer="F.Fab",
    ))

    # 3D model reference
    if model_3d_path:
        kicad_mod.append(Model(
            filename=model_3d_path,
            at=list(model_offset),
            rotate=list(model_rotation),
        ))

    # Write to disk
    lib_dir = os.path.join(output_dir, footprint_lib)
    os.makedirs(lib_dir, exist_ok=True)
    filepath = os.path.join(lib_dir, f"{name}.kicad_mod")

    handler = KicadFileHandler(kicad_mod)
    handler.writeFile(filepath)
    log.info("Footprint '%s' written to %s", name, filepath)
    return name
