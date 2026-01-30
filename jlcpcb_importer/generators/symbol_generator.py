"""Generate KiCad .kicad_sym symbol files from EasyEDA shape data.

Ported from the original JLC2KiCadLib symbol generation logic, restructured
to work with the plugin's data models and API client.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field

from ..api.models import SymbolShapeData
from ..utils.logger import get_logger

log = get_logger()

_LIB_HEADER = (
    '(kicad_symbol_lib (version 20210201) (generator jlcpcb_importer)\n'
)
_LIB_FOOTER = ')\n'

_SUPPORTED_VALUE_TYPES = ("Resistance", "Capacitance", "Inductance", "Frequency")


def _mil2mm(value: float | str) -> float:
    return float(value) / 3.937


def _sanitize_symbol_name(name: str) -> str:
    """Clean a name for use as a KiCad symbol identifier."""
    return (
        name.replace(" ", "_")
        .replace(".", "_")
        .replace("/", "{slash}")
        .replace("\\", "{backslash}")
        .replace("<", "{lt}")
        .replace(">", "{gt}")
        .replace(":", "{colon}")
        .replace('"', "{dblquote}")
    )


# ------------------------------------------------------------------
# Internal drawing accumulator
# ------------------------------------------------------------------


@dataclass
class _SymbolDrawing:
    drawing: str = ""
    pin_names_hide: str = "(pin_names hide)"
    pin_numbers_hide: str = "(pin_numbers hide)"


# ------------------------------------------------------------------
# Shape handlers – same signatures as original, write into _SymbolDrawing
# ------------------------------------------------------------------


def _h_R(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    x1, y1 = float(data[0]), float(data[1])
    width, length = float(data[4]), float(data[5])
    x2, y2 = x1 + width, y1 + length

    x1_mm = _mil2mm(x1 - translation[0])
    y1_mm = -_mil2mm(y1 - translation[1])
    x2_mm = _mil2mm(x2 - translation[0])
    y2_mm = -_mil2mm(y2 - translation[1])

    stroke_map = {"1": "dash", "2": "dot"}
    stroke_style = stroke_map.get(str(data[8]), "default")

    sym.drawing += f"""
      (rectangle
        (start {x1_mm} {y1_mm})
        (end {x2_mm} {y2_mm})
        (stroke (width 0) (type {stroke_style}) (color 0 0 0 0))
        (fill (type background))
      )"""


def _h_E(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    x1 = _mil2mm(float(data[0]) - translation[0])
    y1 = -_mil2mm(float(data[1]) - translation[1])
    radius = _mil2mm(float(data[2]))

    sym.drawing += f"""
      (circle
        (center {x1} {y1})
        (radius {radius})
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type background))
      )"""


def _h_P(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    etype_map = {
        "0": "unspecified", "1": "input", "2": "output",
        "3": "bidirectional", "4": "power_in",
    }
    electrical_type = etype_map.get(data[1], "unspecified")

    pin_number = data[2]
    pin_name = data[13]

    x1 = round(_mil2mm(float(data[3]) - translation[0]), 3)
    y1 = round(-_mil2mm(float(data[4]) - translation[1]), 3)

    rotation = (int(data[5]) + 180) % 360 if data[5] else 180

    if rotation in (0, 180):
        try:
            length = round(_mil2mm(abs(float(data[8].split("h")[-1]))), 3)
        except (ValueError, IndexError):
            length = 2.54
    elif rotation in (90, 270):
        try:
            length = _mil2mm(abs(float(data[8].split("v")[-1])))
        except (ValueError, IndexError):
            length = 2.54
    else:
        length = 2.54
        log.warning("Pin %s '%s': non-standard rotation, using default length", pin_number, pin_name)

    try:
        if data[9].split("^^")[1] != "0":
            sym.pin_names_hide = ""
    except (IndexError, AttributeError):
        pass
    try:
        if data[17].split("^^")[1] != "0":
            sym.pin_numbers_hide = ""
    except (IndexError, AttributeError):
        pass

    name_size = _mil2mm(float(data[16].replace("pt", ""))) if data[16] else 1
    number_size = _mil2mm(float(data[24].replace("pt", ""))) if data[24] else 1

    sym.drawing += f"""
      (pin {electrical_type} line
        (at {x1} {y1} {rotation})
        (length {length})
        (name "{pin_name}" (effects (font (size {name_size} {name_size}))))
        (number "{pin_number}" (effects (font (size {number_size} {number_size}))))
      )"""


def _h_T(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    x1 = _mil2mm(float(data[1]) - translation[0])
    y1 = -_mil2mm(float(data[2]) - translation[1])
    rotation = ((int(data[3]) + 180) % 360) * 10
    font_size = _mil2mm(float(data[6].replace("pt", ""))) if data[6] else 15
    text = data[11]

    justify_map = {"middle": "left", "end": "right"}
    justify = justify_map.get(data[13], "left")

    sym.drawing += f"""
      (text
        "{text}"
        (at {x1} {y1} {rotation})
        (effects
            (font (size {font_size} {font_size}))
            (justify {justify} bottom)
        )
      )"""


def _h_PL(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    path_string = data[0].split(" ")
    polypts = []
    for i in range(len(path_string) // 2):
        polypts.append(
            f"(xy {_mil2mm(float(path_string[2 * i]) - translation[0])} "
            f"{-_mil2mm(float(path_string[2 * i + 1]) - translation[-1])})"
        )
    polystr = "\n          ".join(polypts)

    sym.drawing += f"""
      (polyline
        (pts
          {polystr}
        )
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type none))
      )"""


def _h_PG(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    path_string = [i for i in data[0].split(" ") if i]
    polypts = []
    for i in range(len(path_string) // 2):
        polypts.append(
            f"(xy {_mil2mm(float(path_string[2 * i]) - translation[0])} "
            f"{-_mil2mm(float(path_string[2 * i + 1]) - translation[1])})"
        )
    polypts.append(polypts[0])
    polystr = "\n          ".join(polypts)

    sym.drawing += f"""
      (polyline
        (pts
          {polystr}
        )
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type background))
      )"""


def _h_PT(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    data[0] = data[0].replace("M", "").replace("L", "").replace("Z", "").replace("C", "")
    _h_PG(data, translation, sym)


def _h_A(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    path = data[0].strip()
    parts = re.split(r"[MA]", path)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < 2:
        return

    start_coords = re.split(r"[\s,]+", parts[0])
    x1, y1 = float(start_coords[0]), float(start_coords[1])

    arc_params = re.split(r"[\s,]+", parts[1])
    rx, ry = float(arc_params[0]), float(arc_params[1])
    rotation = float(arc_params[2])
    large_arc_flag = int(arc_params[3])
    sweep_flag = int(arc_params[4])
    x2, y2 = float(arc_params[5]), float(arc_params[6])

    cos_rot = math.cos(math.radians(rotation))
    sin_rot = math.sin(math.radians(rotation))

    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p = cos_rot * dx + sin_rot * dy
    y1p = -sin_rot * dx + cos_rot * dy

    rx_sq, ry_sq = rx * rx, ry * ry
    x1p_sq, y1p_sq = x1p * x1p, y1p * y1p

    lam = x1p_sq / rx_sq + y1p_sq / ry_sq
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
        rx_sq, ry_sq = rx * rx, ry * ry

    sign = -1 if large_arc_flag == sweep_flag else 1
    denom = rx_sq * y1p_sq + ry_sq * x1p_sq
    if denom == 0:
        return

    sq = max(0, (rx_sq * ry_sq - rx_sq * y1p_sq - ry_sq * x1p_sq) / denom)
    coef = sign * math.sqrt(sq)
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx

    cx = cos_rot * cxp - sin_rot * cyp + (x1 + x2) / 2
    cy = sin_rot * cxp + cos_rot * cyp + (y1 + y2) / 2

    def _angle(ux, uy, vx, vy):
        n = math.sqrt(ux * ux + uy * uy) * math.sqrt(vx * vx + vy * vy)
        c = max(-1, min(1, (ux * vx + uy * vy) / n))
        a = math.acos(c)
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry,
        (-x1p - cxp) / rx, (-y1p - cyp) / ry,
    )
    if sweep_flag == 0 and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep_flag == 1 and dtheta < 0:
        dtheta += 2 * math.pi

    mid_angle = theta1 + dtheta / 2
    x_mid = cx + rx * math.cos(mid_angle) * cos_rot - ry * math.sin(mid_angle) * sin_rot
    y_mid = cy + rx * math.cos(mid_angle) * sin_rot + ry * math.sin(mid_angle) * cos_rot

    x1_mm = _mil2mm(x1 - translation[0])
    y1_mm = -_mil2mm(y1 - translation[1])
    x2_mm = _mil2mm(x2 - translation[0])
    y2_mm = -_mil2mm(y2 - translation[1])
    xm_mm = _mil2mm(x_mid - translation[0])
    ym_mm = -_mil2mm(y_mid - translation[1])

    sym.drawing += f"""
      (arc
        (start {x1_mm} {y1_mm})
        (mid {xm_mm} {ym_mm})
        (end {x2_mm} {y2_mm})
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type none))
      )"""


def _h_AR(data: list[str], translation: tuple, sym: _SymbolDrawing) -> None:
    svg_path = data[5]
    path_cleaned = svg_path.replace("M", "").replace("L", "").replace("Z", "").strip()
    coords = [c for c in re.split(r"[\s,]+", path_cleaned) if c]

    polypts = []
    for i in range(0, len(coords) - 1, 2):
        x, y = float(coords[i]), float(coords[i + 1])
        polypts.append(
            f"(xy {_mil2mm(x - translation[0])} {-_mil2mm(y - translation[1])})"
        )
    if not polypts:
        return

    polypts.append(polypts[0])
    polystr = "\n          ".join(polypts)

    sym.drawing += f"""
      (polyline
        (pts
          {polystr}
        )
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type background))
      )"""


_HANDLERS: dict[str, callable] = {
    "R": _h_R, "E": _h_E, "P": _h_P, "T": _h_T,
    "PL": _h_PL, "PG": _h_PG, "PT": _h_PT, "A": _h_A, "AR": _h_AR,
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def _build_value_properties(start_id: int, type_values: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'(property "{tv[0]}" "{tv[1]}" (id {start_id + i}) (at 0 0 0)\n'
        f'      (effects (font (size 1.27 1.27)) hide)\n'
        f'    )'
        for i, tv in enumerate(type_values)
    )


def generate_symbol(
    symbol_data_list: list[SymbolShapeData],
    footprint_name: str,
    datasheet_link: str,
    component_id: str,
    library_name: str,
    output_dir: str,
    skip_existing: bool = False,
) -> str | None:
    """Generate a KiCad symbol and write it into a .kicad_sym library file.

    Args:
        symbol_data_list: One or more SymbolShapeData objects (multi-unit support).
        footprint_name: KiCad footprint reference (e.g. ``"JLCPCB_Footprints:C12345"``).
        datasheet_link: URL to the component datasheet.
        component_id: LCSC part number.
        library_name: Name of the symbol library (without extension).
        output_dir: Directory containing the library file.
        skip_existing: If True, don't overwrite existing symbols.

    Returns:
        The symbol name on success, or None on failure.
    """
    sym = _SymbolDrawing()
    component_name = ""
    prefix = "U"
    type_values: list[tuple[str, str]] = []

    for idx, sdata in enumerate(symbol_data_list):
        title = _sanitize_symbol_name(sdata.name)

        if sdata.value_field and sdata.value_type:
            type_values.append((sdata.value_type, sdata.value_field))

        raw_prefix = sdata.prefix.replace("?", "")
        if raw_prefix:
            prefix = raw_prefix

        if not component_name:
            component_name = title
            title += "_0"

        # For multi-unit: skip first unit's drawing pass (collected above)
        if len(symbol_data_list) >= 2 and idx == 0:
            continue

        sym.drawing += f'\n    (symbol "{title}_1"'

        for line in sdata.shapes:
            args = line.split("~")
            model = args[0]
            if model in _HANDLERS:
                _HANDLERS[model](args[1:], sdata.translation, sym)
            else:
                log.debug("symbol handler not found: %s", model)

        sym.drawing += "\n    )"

    if not component_name:
        log.error("No symbol data to generate")
        return None

    if not library_name:
        library_name = component_name

    # Build the full symbol S-expression
    value_props = _build_value_properties(6, type_values)
    template = (
        f'  (symbol "{component_name}" {sym.pin_names_hide} '
        f'{sym.pin_numbers_hide} (in_bom yes) (on_board yes)\n'
        f'    (property "Reference" "{prefix}" (id 0) (at 0 1.27 0)\n'
        f'      (effects (font (size 1.27 1.27)))\n'
        f'    )\n'
        f'    (property "Value" "{component_name}" (id 1) (at 0 -2.54 0)\n'
        f'      (effects (font (size 1.27 1.27)))\n'
        f'    )\n'
        f'    (property "Footprint" "{footprint_name}" (id 2) (at 0 -10.16 0)\n'
        f'      (effects (font (size 1.27 1.27) italic) hide)\n'
        f'    )\n'
        f'    (property "Datasheet" "{datasheet_link}" (id 3) (at -2.286 0.127 0)\n'
        f'      (effects (font (size 1.27 1.27)) (justify left) hide)\n'
        f'    )\n'
        f'    (property "ki_keywords" "{component_id}" (id 4) (at 0 0 0)\n'
        f'      (effects (font (size 1.27 1.27)) hide)\n'
        f'    )\n'
        f'    (property "LCSC" "{component_id}" (id 5) (at 0 0 0)\n'
        f'      (effects (font (size 1.27 1.27)) hide)\n'
        f'    )\n'
        f'    {value_props}{sym.drawing}\n'
        f'  )\n'
    )

    # Write / update library file
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"{library_name}.kicad_sym")

    if not os.path.isfile(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(_LIB_HEADER)
            f.write(_LIB_FOOTER)

    _update_library(filepath, component_name, template, skip_existing)
    log.info("Symbol '%s' written to %s", component_name, filepath)
    return component_name


def _update_library(
    filepath: str,
    component_name: str,
    template: str,
    skip_existing: bool,
) -> None:
    """Insert or replace a symbol definition in a .kicad_sym file."""
    with open(filepath, "rb+") as f:
        content = f.read().decode("utf-8")

    marker = f'symbol "{component_name}"'
    if marker in content:
        if skip_existing:
            log.info("Symbol '%s' already exists, skipping", component_name)
            return
        pattern = rf'  \(symbol "{re.escape(component_name)}" (\n|.)*?\n  \)'
        content = re.sub(pattern, template, content, count=1, flags=re.DOTALL)
        log.info("Updated existing symbol '%s'", component_name)
    else:
        # Insert before the final closing paren
        insert_pos = content.rfind(")")
        content = content[:insert_pos] + template + _LIB_FOOTER
        log.info("Appended new symbol '%s'", component_name)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
