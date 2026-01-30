"""Download and convert 3D models (STEP and WRL) from EasyEDA.

STEP files are downloaded as binary blobs.  WRL (VRML 2.0) files are
built by converting the OBJ/MTL text data returned by the EasyEDA API
into VRML geometry.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..api.jlcpcb_client import JLCPCBClient

log = get_logger()

_WRL_HEADER = """#VRML V2.0 utf8
#created by jlcpcb_importer KiCad plugin
#https://github.com/TousstNicolas/JLC2KiCad_lib
"""


def _mil2mm(value: float | str) -> float:
    return float(value) / 3.937


def download_step_model(
    client: JLCPCBClient,
    component_uuid: str,
    output_dir: str,
    filename: str,
) -> str | None:
    """Download a STEP 3D model and write it to disk.

    Args:
        client: The API client instance.
        component_uuid: EasyEDA component UUID.
        output_dir: Directory to write the model file into.
        filename: Output filename (without extension).

    Returns:
        Full path to the written file, or None if unavailable.
    """
    data = client.download_step_model(component_uuid)
    if data is None:
        return None

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{filename}.step")
    with open(path, "wb") as f:
        f.write(data)
    log.info("STEP model saved to %s", path)
    return path


def download_wrl_model(
    client: JLCPCBClient,
    component_uuid: str,
    output_dir: str,
    filename: str,
) -> str | None:
    """Download OBJ/MTL data and convert it to VRML 2.0 (WRL).

    Args:
        client: The API client instance.
        component_uuid: EasyEDA component UUID.
        output_dir: Directory to write the model file into.
        filename: Output filename (without extension).

    Returns:
        Full path to the written file, or None if unavailable.
    """
    text = client.download_wrl_model(component_uuid)
    if text is None:
        return None

    wrl_content = _WRL_HEADER

    # Parse materials
    materials: dict[str, dict] = {}
    for m in re.findall(r"newmtl .*?endmtl", text, re.DOTALL):
        mat: dict = {}
        mat_id = ""
        for line in m.split("\n"):
            if line.startswith("newmtl"):
                mat_id = line.split(" ")[1]
            elif line.startswith("Ka"):
                mat["ambientColor"] = line.split(" ")[1:]
            elif line.startswith("Kd"):
                mat["diffuseColor"] = line.split(" ")[1:]
            elif line.startswith("Ks"):
                mat["specularColor"] = line.split(" ")[1:]
            elif line.startswith("d"):
                mat["transparency"] = line.split(" ")[1]
        if mat_id:
            materials[mat_id] = mat

    # Parse vertices (convert inches → mm via /2.54)
    vertices: list[str] = []
    for v in re.findall(r"v (.*?)\n", text, re.DOTALL):
        vertices.append(
            " ".join(str(round(float(c) / 2.54, 4)) for c in v.split(" "))
        )

    # Parse shapes
    for shape in text.split("usemtl")[1:]:
        lines = shape.split("\n")
        mat_key = lines[0].replace(" ", "")
        if mat_key not in materials:
            continue
        material = materials[mat_key]

        index_counter = 0
        link_dict: dict[int, int] = {}
        coord_index: list[str] = []
        points: list[str] = []

        for line in lines[1:]:
            if not line:
                continue
            face = [int(idx) for idx in line.replace("//", "").split(" ")[1:]]
            face_idx: list[str] = []
            for idx in face:
                if idx not in link_dict:
                    link_dict[idx] = index_counter
                    face_idx.append(str(index_counter))
                    points.append(vertices[idx - 1])
                    index_counter += 1
                else:
                    face_idx.append(str(link_dict[idx]))
            face_idx.append("-1")
            coord_index.append(",".join(face_idx) + ",")

        if points:
            points.insert(-1, points[-1])

        diff_color = " ".join(material.get("diffuseColor", ["0.8", "0.8", "0.8"]))
        spec_color = " ".join(material.get("specularColor", ["0", "0", "0"]))
        transparency = material.get("transparency", "0")

        wrl_content += f"""
Shape{{
\tappearance Appearance {{
\t\tmaterial  Material \t{{
\t\t\tdiffuseColor {diff_color}
\t\t\tspecularColor {spec_color}
\t\t\tambientIntensity 0.2
\t\t\ttransparency {transparency}
\t\t\tshininess 0.5
\t\t}}
\t}}
\tgeometry IndexedFaceSet {{
\t\tccw TRUE
\t\tsolid FALSE
\t\tcoord DEF co Coordinate {{
\t\t\tpoint [
\t\t\t\t{', '.join(points)}
\t\t\t]
\t\t}}
\t\tcoordIndex [
\t\t\t{''.join(coord_index)}
\t\t]
\t}}
}}"""

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{filename}.wrl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(wrl_content)
    log.info("WRL model saved to %s", path)
    return path


def compute_model_transform(
    origin_x: float,
    origin_y: float,
    origin_z: float,
    fp_origin: tuple[float, float],
    rotation_str: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Compute the 3D model offset and rotation for a footprint.

    Args:
        origin_x: Model X origin (mils).
        origin_y: Model Y origin (mils).
        origin_z: Model Z origin.
        fp_origin: Footprint origin (x, y) in mils.
        rotation_str: Comma-separated rotation string (e.g. ``"0,0,90"``).

    Returns:
        ``(offset_tuple, rotation_tuple)`` both as ``(x, y, z)``.
    """
    tx = (origin_x - fp_origin[0]) / 100
    ty = -(origin_y - fp_origin[1]) / 100
    tz = float(origin_z) / 100

    rot = [-float(a) for a in rotation_str.split(",")]
    while len(rot) < 3:
        rot.append(0.0)

    return (tx, ty, tz), tuple(rot[:3])


def parse_svgnode_attrs(json_str: str) -> dict | None:
    """Extract 3D model attributes from an SVGNODE JSON string.

    Returns a dict with keys ``uuid``, ``origin_x``, ``origin_y``,
    ``origin_z``, ``rotation`` – or None on parse failure.
    """
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None

    attrs = parsed.get("attrs", {})
    c_origin = attrs.get("c_origin", "0,0").split(",")
    return {
        "uuid": attrs.get("uuid", ""),
        "origin_x": float(c_origin[0]) if len(c_origin) >= 1 else 0.0,
        "origin_y": float(c_origin[1]) if len(c_origin) >= 2 else 0.0,
        "origin_z": attrs.get("z", "0"),
        "rotation": attrs.get("c_rotation", "0,0,0"),
    }
