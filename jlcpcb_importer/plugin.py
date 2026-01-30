"""KiCad ActionPlugin entry point.

This module registers the JLCPCB Importer as a KiCad plugin.  When
running outside KiCad (e.g. during tests), the pcbnew import is
gracefully skipped.

The plugin directory is added to sys.path so that the ``jlcpcb_importer``
package and the vendored ``KicadModTree`` can be resolved at runtime.
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Path setup – ensure the project root (parent of jlcpcb_importer/) is on
# sys.path so both ``jlcpcb_importer`` and ``vendor`` resolve correctly.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .utils.logger import get_logger  # noqa: E402

log = get_logger()

# pcbnew is only available inside the KiCad Python environment
try:
    import pcbnew

    _HAS_PCBNEW = True
except ImportError:
    _HAS_PCBNEW = False


if _HAS_PCBNEW:

    class JLCPCBImporterPlugin(pcbnew.ActionPlugin):
        """KiCad ActionPlugin that opens the JLCPCB import dialog."""

        def defaults(self) -> None:
            self.name = "JLCPCB Component Importer"
            self.category = "Import"
            self.description = (
                "Import components from JLCPCB/LCSC with automatic symbol, "
                "footprint, and 3D model generation."
            )
            self.show_toolbar_button = True
            icon_path = os.path.join(_THIS_DIR, "icon.png")
            if os.path.isfile(icon_path):
                self.icon_file_name = icon_path

        def Run(self) -> None:
            """Called when the user activates the plugin."""
            log.info("JLCPCB Importer plugin activated")
            try:
                from .ui.import_dialog import show_import_dialog
                show_import_dialog()
            except Exception:
                log.exception("Failed to launch import dialog")

    # Register with KiCad
    JLCPCBImporterPlugin().register()

else:

    class JLCPCBImporterPlugin:
        """Stub for environments where pcbnew is not available."""

        def __init__(self) -> None:
            log.debug(
                "pcbnew not available; plugin registration skipped"
            )
