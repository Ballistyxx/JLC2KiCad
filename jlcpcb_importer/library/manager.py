"""Library path manager for JLCPCB-imported components.

Creates and manages a project-specific library directory structure:

    jlcpcb_lib/
    ├── symbols/
    │   └── jlcpcb_parts.kicad_sym
    ├── footprints.pretty/
    │   └── C12345.kicad_mod
    └── 3dmodels/
        └── C12345.step
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils.logger import get_logger

log = get_logger()


class LibraryManager:
    """Manage the per-project library directory tree.

    All paths are resolved relative to the KiCad project root.
    """

    def __init__(
        self,
        project_dir: str,
        lib_dir_name: str = "jlcpcb_lib",
        symbol_lib_name: str = "jlcpcb_parts",
        footprint_lib_name: str = "JLCPCB_Footprints.pretty",
        models_dir_name: str = "3dmodels",
    ) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.lib_root = os.path.join(self.project_dir, lib_dir_name)
        self.symbols_dir = os.path.join(self.lib_root, "symbols")
        self.footprints_dir = os.path.join(self.lib_root, footprint_lib_name)
        self.models_dir = os.path.join(self.lib_root, models_dir_name)
        self.symbol_lib_name = symbol_lib_name
        self._footprint_lib_name = footprint_lib_name

    # ------------------------------------------------------------------
    # Path accessors
    # ------------------------------------------------------------------

    @property
    def symbol_lib_path(self) -> str:
        """Absolute path to the .kicad_sym file."""
        return os.path.join(self.symbols_dir, f"{self.symbol_lib_name}.kicad_sym")

    def footprint_path(self, name: str) -> str:
        """Absolute path to a specific .kicad_mod file."""
        return os.path.join(self.footprints_dir, f"{name}.kicad_mod")

    def model_path(self, name: str, ext: str = "step") -> str:
        """Absolute path to a 3D model file."""
        return os.path.join(self.models_dir, f"{name}.{ext}")

    @property
    def kicad_footprint_ref(self) -> str:
        """Library reference string for use in KiCad symbol footprint fields.

        Returns something like ``"JLCPCB_Footprints"`` (without ``.pretty``).
        """
        return self._footprint_lib_name.replace(".pretty", "")

    def model_ref(self, name: str, ext: str = "step") -> str:
        """Model reference path using ``${KIPRJMOD}`` variable.

        Returns e.g.
        ``"${KIPRJMOD}/jlcpcb_lib/3dmodels/C12345.step"``
        """
        rel = os.path.relpath(self.model_path(name, ext), self.project_dir)
        return "${KIPRJMOD}/" + rel.replace("\\", "/")

    def symbol_lib_uri(self) -> str:
        """URI for sym-lib-table using ``${KIPRJMOD}``."""
        rel = os.path.relpath(self.symbol_lib_path, self.project_dir)
        return "${KIPRJMOD}/" + rel.replace("\\", "/")

    def footprint_lib_uri(self) -> str:
        """URI for fp-lib-table using ``${KIPRJMOD}``."""
        rel = os.path.relpath(self.footprints_dir, self.project_dir)
        return "${KIPRJMOD}/" + rel.replace("\\", "/")

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def ensure_directories(self) -> None:
        """Create the full library directory tree if it doesn't exist."""
        for d in (self.symbols_dir, self.footprints_dir, self.models_dir):
            Path(d).mkdir(parents=True, exist_ok=True)
            log.debug("Ensured directory: %s", d)

    def is_writable(self) -> bool:
        """Check that the project directory is writable."""
        return os.access(self.project_dir, os.W_OK)

    @staticmethod
    def detect_project_dir() -> str | None:
        """Try to detect the KiCad project directory.

        Looks for a ``.kicad_pro`` file by trying the pcbnew board
        filename first, then falling back to the current working
        directory.
        """
        # Try pcbnew API first
        try:
            import pcbnew
            board = pcbnew.GetBoard()
            if board:
                board_file = board.GetFileName()
                if board_file:
                    return str(Path(board_file).parent)
        except (ImportError, AttributeError):
            pass

        # Fallback: CWD
        cwd = os.getcwd()
        for f in os.listdir(cwd):
            if f.endswith(".kicad_pro"):
                return cwd
        return None
