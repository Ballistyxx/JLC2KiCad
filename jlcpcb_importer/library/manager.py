"""Library path manager for JLCPCB-imported components.

Supports two modes:

**Project mode** (``is_global=False``, the classic behaviour):

    <project>/
    └── jlcpcb_lib/
        ├── symbols/jlcpcb_parts.kicad_sym
        ├── JLCPCB_Footprints.pretty/C12345.kicad_mod
        └── 3dmodels/C12345.step

Library URIs use ``${KIPRJMOD}`` so the library is portable within the
project.  Entries are written to the project-level ``sym-lib-table`` /
``fp-lib-table``.

**Global mode** (``is_global=True``):

    ~/.local/share/kicad/<version>/libraries/jlcpcb_parts/
    ├── symbols/jlcpcb_parts.kicad_sym
    ├── JLCPCB_Footprints.pretty/C12345.kicad_mod
    └── 3dmodels/C12345.step

Library URIs are absolute paths.  Entries are written to the global
``~/.local/share/kicad/<version>/sym-lib-table`` / ``fp-lib-table`` so
every project on the machine can use them without any extra setup.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils.logger import get_logger

log = get_logger()

_GLOBAL_LIB_SUBDIR = os.path.join("libraries", "jlcpcb_parts")


class LibraryManager:
    """Manage the library directory tree.

    In *project* mode ``project_dir`` is the KiCad project folder and files
    land in ``<project_dir>/jlcpcb_lib/``.

    In *global* mode ``project_dir`` must be the KiCad user-data directory
    (e.g. ``~/.local/share/kicad/9.0``) and files land in
    ``<kicad_user_dir>/libraries/jlcpcb_parts/``.  Pass
    ``lib_dir_name=_GLOBAL_LIB_SUBDIR`` together with ``is_global=True``
    (done automatically by the dialog when global mode is selected).
    """

    def __init__(
        self,
        project_dir: str,
        is_global: bool = False,
        lib_dir_name: str = "jlcpcb_lib",
        symbol_lib_name: str = "jlcpcb_parts",
        footprint_lib_name: str = "JLCPCB_Footprints.pretty",
        models_dir_name: str = "3dmodels",
    ) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.is_global = is_global
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
        """Model reference path for embedding in a .kicad_mod file.

        In project mode returns ``"${KIPRJMOD}/jlcpcb_lib/3dmodels/C12345.step"``.
        In global mode returns the absolute POSIX path so the model is found
        regardless of which project is open.
        """
        abs_path = self.model_path(name, ext)
        if self.is_global:
            return Path(abs_path).as_posix()
        rel = os.path.relpath(abs_path, self.project_dir)
        return "${KIPRJMOD}/" + rel.replace("\\", "/")

    def symbol_lib_uri(self) -> str:
        """URI written into sym-lib-table."""
        if self.is_global:
            return Path(self.symbol_lib_path).as_posix()
        rel = os.path.relpath(self.symbol_lib_path, self.project_dir)
        return "${KIPRJMOD}/" + rel.replace("\\", "/")

    def footprint_lib_uri(self) -> str:
        """URI written into fp-lib-table."""
        if self.is_global:
            return Path(self.footprints_dir).as_posix()
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
    def detect_kicad_user_dir() -> str | None:
        """Return the versioned KiCad user-data directory.

        Looks under ``$XDG_DATA_HOME/kicad/`` (typically
        ``~/.local/share/kicad/``) and returns the highest-version
        subdirectory found, e.g. ``~/.local/share/kicad/9.0``.
        """
        kicad_base = os.path.join(
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
            "kicad",
        )
        if not os.path.isdir(kicad_base):
            return None
        versions = sorted(
            (
                d for d in os.listdir(kicad_base)
                if os.path.isdir(os.path.join(kicad_base, d))
            ),
            key=lambda v: [int(x) if x.isdigit() else x for x in v.split(".")],
        )
        if not versions:
            return None
        return os.path.join(kicad_base, versions[-1])

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
