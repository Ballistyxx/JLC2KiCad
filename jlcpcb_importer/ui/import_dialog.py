"""Main import dialog for the JLCPCB Component Importer plugin.

Provides a wxPython dialog where the user enters an LCSC part number,
previews the component details, and triggers the import pipeline.
"""

from __future__ import annotations

import os
import re
import threading
from typing import TYPE_CHECKING

import wx

from ..api.cache import ComponentCache
from ..api.jlcpcb_client import ApiError, JLCPCBClient
from ..api.models import PartData
from ..generators.footprint_generator import generate_footprint
from ..generators.model_3d_generator import (
    compute_model_transform,
    download_step_model,
    download_wrl_model,
    parse_svgnode_attrs,
)
from ..generators.symbol_generator import generate_symbol
from ..library.manager import LibraryManager
from ..library.table_editor import ensure_footprint_table, ensure_symbol_table
from ..utils.config import PluginConfig, load_config
from ..utils.logger import get_logger
from .preview_panel import PreviewPanel

log = get_logger()

_LCSC_RE = re.compile(r"^C\d+$", re.IGNORECASE)


class ImportDialog(wx.Dialog):
    """Main dialog for importing a JLCPCB/LCSC component."""

    def __init__(self, parent: wx.Window | None, config: PluginConfig | None = None) -> None:
        super().__init__(
            parent,
            title="Import JLCPCB Component",
            size=(520, 460),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._config = config or load_config()
        self._client = JLCPCBClient(self._config.api)
        self._cache = ComponentCache(self._config.cache)
        self._part_data: PartData | None = None
        self._project_dir: str | None = None

        self._build_ui()
        self.CenterOnParent()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # -- Input row --
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        input_sizer.Add(
            wx.StaticText(panel, label="LCSC Part #:"),
            0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8,
        )
        self._part_input = wx.TextCtrl(
            panel, style=wx.TE_PROCESS_ENTER, size=(180, -1),
        )
        self._part_input.SetHint("e.g. C25804")
        self._part_input.Bind(wx.EVT_TEXT_ENTER, self._on_fetch)
        input_sizer.Add(self._part_input, 1, wx.EXPAND | wx.RIGHT, 8)

        self._fetch_btn = wx.Button(panel, label="Fetch")
        self._fetch_btn.Bind(wx.EVT_BUTTON, self._on_fetch)
        input_sizer.Add(self._fetch_btn, 0)

        main_sizer.Add(input_sizer, 0, wx.EXPAND | wx.ALL, 12)

        # -- Separator --
        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # -- Preview panel --
        self._preview = PreviewPanel(panel)
        main_sizer.Add(self._preview, 1, wx.EXPAND | wx.ALL, 12)

        # -- Options --
        opts_box = wx.StaticBox(panel, label="Options")
        opts_sizer = wx.StaticBoxSizer(opts_box, wx.VERTICAL)

        self._chk_3d = wx.CheckBox(panel, label="Download 3D model (STEP)")
        self._chk_3d.SetValue(self._config.download_3d_models != "never")
        opts_sizer.Add(self._chk_3d, 0, wx.ALL, 4)

        main_sizer.Add(opts_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # -- Status bar --
        self._status = wx.StaticText(panel, label="")
        self._status.SetForegroundColour(wx.Colour(100, 100, 100))
        main_sizer.Add(self._status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # -- Buttons --
        btn_sizer = wx.StdDialogButtonSizer()
        self._import_btn = wx.Button(panel, wx.ID_OK, "Import")
        self._import_btn.Bind(wx.EVT_BUTTON, self._on_import)
        self._import_btn.Disable()
        btn_sizer.AddButton(self._import_btn)

        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        panel.SetSizer(main_sizer)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_fetch(self, event: wx.Event) -> None:
        raw = self._part_input.GetValue().strip().upper()
        if not _LCSC_RE.match(raw):
            self._set_status("Invalid part number. Expected format: C12345", error=True)
            return

        self._set_status(f"Fetching {raw} ...")
        self._fetch_btn.Disable()
        self._import_btn.Disable()

        # Run fetch in background thread to keep UI responsive
        thread = threading.Thread(target=self._fetch_part, args=(raw,), daemon=True)
        thread.start()

    def _fetch_part(self, lcsc: str) -> None:
        """Background thread: fetch part data and update UI."""
        try:
            # Check cache first
            cached = self._cache.get(lcsc, "part_info")
            if cached:
                part = PartData.from_dict(cached)
            else:
                part = self._client.get_part_info(lcsc)
                self._cache.put(lcsc, part.to_dict(), "part_info")

            wx.CallAfter(self._on_fetch_ok, part)
        except ApiError as exc:
            wx.CallAfter(self._on_fetch_error, str(exc))
        except Exception as exc:
            wx.CallAfter(self._on_fetch_error, f"Unexpected error: {exc}")

    def _on_fetch_ok(self, part: PartData) -> None:
        self._part_data = part
        self._preview.show_part(part)
        self._import_btn.Enable()
        self._fetch_btn.Enable()
        self._set_status(f"Ready to import {part.lcsc_number}")

    def _on_fetch_error(self, msg: str) -> None:
        self._part_data = None
        self._preview.show_error(msg)
        self._import_btn.Disable()
        self._fetch_btn.Enable()
        self._set_status(msg, error=True)

    def _on_import(self, event: wx.Event) -> None:
        if not self._part_data:
            return

        # Detect project directory
        project_dir = self._detect_project_dir()
        if not project_dir:
            wx.MessageBox(
                "Could not detect KiCad project directory.\n"
                "Please open a project in KiCad first.",
                "Error", wx.OK | wx.ICON_ERROR, self,
            )
            return

        self._set_status(f"Importing {self._part_data.lcsc_number} ...")
        self._import_btn.Disable()
        self._fetch_btn.Disable()

        thread = threading.Thread(
            target=self._run_import,
            args=(self._part_data, project_dir),
            daemon=True,
        )
        thread.start()

    def _run_import(self, part: PartData, project_dir: str) -> None:
        """Background thread: run the full import pipeline."""
        try:
            lib_mgr = LibraryManager(project_dir)
            lib_mgr.ensure_directories()

            lcsc = part.lcsc_number
            uuids = self._client.get_component_uuids(lcsc)

            # -- Footprint --
            wx.CallAfter(self._set_status, "Generating footprint ...")
            fp_data = self._client.get_footprint_data(uuids.footprint_uuid)

            # Extract 3D model info from SVGNODE shapes
            model_3d_path = None
            model_offset = (0, 0, 0)
            model_rotation = (0, 0, 0)

            if self._chk_3d.GetValue():
                for line in fp_data.shapes:
                    if line.startswith("SVGNODE"):
                        args = line.split("~")
                        attrs = parse_svgnode_attrs(args[1]) if len(args) > 1 else None
                        if attrs and attrs["uuid"]:
                            wx.CallAfter(self._set_status, "Downloading 3D model ...")
                            step_path = download_step_model(
                                self._client, attrs["uuid"],
                                lib_mgr.models_dir, fp_data.name or lcsc,
                            )
                            if step_path:
                                model_offset, model_rotation = compute_model_transform(
                                    attrs["origin_x"], attrs["origin_y"],
                                    attrs["origin_z"],
                                    fp_data.translation,
                                    attrs["rotation"],
                                )
                                model_3d_path = lib_mgr.model_ref(
                                    fp_data.name or lcsc, "step"
                                )
                            break

            fp_name = generate_footprint(
                fp_data=fp_data,
                component_id=lcsc,
                output_dir=lib_mgr.lib_root,
                footprint_lib=os.path.basename(lib_mgr.footprints_dir),
                model_3d_path=model_3d_path,
                model_offset=model_offset,
                model_rotation=model_rotation,
            )

            # -- Symbol --
            wx.CallAfter(self._set_status, "Generating symbol ...")
            sym_data_list = []
            for uuid in uuids.symbol_uuids:
                sym_data_list.append(self._client.get_symbol_data(uuid))

            footprint_ref = (
                f"{lib_mgr.kicad_footprint_ref}:{fp_name}" if fp_name else ""
            )
            datasheet = part.datasheet_url or ""

            generate_symbol(
                symbol_data_list=sym_data_list,
                footprint_name=footprint_ref,
                datasheet_link=datasheet,
                component_id=lcsc,
                library_name=lib_mgr.symbol_lib_name,
                output_dir=lib_mgr.symbols_dir,
            )

            # -- Library tables --
            wx.CallAfter(self._set_status, "Updating library tables ...")
            ensure_symbol_table(
                project_dir,
                lib_mgr.symbol_lib_name,
                lib_mgr.symbol_lib_uri(),
            )
            ensure_footprint_table(
                project_dir,
                lib_mgr.kicad_footprint_ref,
                lib_mgr.footprint_lib_uri(),
            )

            wx.CallAfter(self._on_import_ok, lcsc)

        except Exception as exc:
            log.exception("Import failed")
            wx.CallAfter(self._on_import_error, str(exc))

    def _on_import_ok(self, lcsc: str) -> None:
        self._set_status(f"Successfully imported {lcsc}!")
        self._fetch_btn.Enable()
        self._import_btn.Enable()
        wx.MessageBox(
            f"Component {lcsc} imported successfully.\n\n"
            "The symbol and footprint libraries have been added to your project.\n"
            "You can now place the symbol from the 'jlcpcb_parts' library.",
            "Import Complete",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _on_import_error(self, msg: str) -> None:
        self._set_status(f"Import failed: {msg}", error=True)
        self._fetch_btn.Enable()
        self._import_btn.Enable()
        wx.MessageBox(
            f"Import failed:\n\n{msg}",
            "Error",
            wx.OK | wx.ICON_ERROR,
            self,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        self._status.SetLabel(msg)
        self._status.SetForegroundColour(
            wx.Colour(200, 0, 0) if error else wx.Colour(100, 100, 100)
        )

    def _detect_project_dir(self) -> str | None:
        if self._project_dir:
            return self._project_dir
        return LibraryManager.detect_project_dir()

    def set_project_dir(self, path: str) -> None:
        """Override the project directory (useful for testing)."""
        self._project_dir = path


def show_import_dialog(parent: wx.Window | None = None) -> None:
    """Show the import dialog.  Call from the KiCad plugin's Run()."""
    dlg = ImportDialog(parent)
    dlg.ShowModal()
    dlg.Destroy()
