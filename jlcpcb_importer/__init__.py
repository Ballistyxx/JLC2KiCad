"""JLCPCB Component Importer - KiCad Plugin.

Import JLCPCB/LCSC parts directly into KiCad schematics with automatic
symbol, footprint, and 3D model generation.

When this package is loaded by KiCad's plugin system, the ActionPlugin
is registered automatically via ``plugin.py``.
"""

from __future__ import annotations

import os
import sys

__version__ = "0.1.0"

# Ensure the project root is on sys.path so ``vendor.KicadModTree``
# and other sibling packages resolve correctly.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PKG_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from .plugin import JLCPCBImporterPlugin  # noqa: F401
except Exception:
    # Not running inside KiCad, or wx not available – allow standalone import
    pass
