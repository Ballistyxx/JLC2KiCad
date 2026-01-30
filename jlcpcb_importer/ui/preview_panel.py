"""Component preview panel for the import dialog.

Displays part metadata (manufacturer, MPN, package, description, stock,
price) in a formatted layout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

if TYPE_CHECKING:
    from ..api.models import PartData


class PreviewPanel(wx.Panel):
    """Panel that shows component details after a successful fetch."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)

        self._sizer = wx.BoxSizer(wx.VERTICAL)

        # Title
        self._title = wx.StaticText(self, label="")
        title_font = self._title.GetFont()
        title_font.SetPointSize(title_font.GetPointSize() + 2)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._title.SetFont(title_font)
        self._sizer.Add(self._title, 0, wx.BOTTOM, 8)

        # Detail grid
        self._grid = wx.FlexGridSizer(cols=2, vgap=4, hgap=12)
        self._grid.AddGrowableCol(1, 1)

        self._labels: dict[str, tuple[wx.StaticText, wx.StaticText]] = {}
        for field in (
            "Manufacturer", "MPN", "Package", "Description",
            "LCSC #", "Datasheet",
        ):
            label = wx.StaticText(self, label=f"{field}:")
            label.SetFont(label.GetFont().Bold())
            value = wx.StaticText(self, label="—")
            self._grid.Add(label, 0, wx.ALIGN_TOP)
            self._grid.Add(value, 1, wx.EXPAND)
            self._labels[field] = (label, value)

        self._sizer.Add(self._grid, 1, wx.EXPAND)

        self.SetSizer(self._sizer)
        self.clear()

    def clear(self) -> None:
        """Reset the panel to its empty state."""
        self._title.SetLabel("No component loaded")
        for _, (_, v) in self._labels.items():
            v.SetLabel("—")
        self.Layout()

    def show_part(self, part: PartData) -> None:
        """Populate the panel with data from a PartData object."""
        self._title.SetLabel(part.mpn or part.lcsc_number)

        field_map = {
            "Manufacturer": part.manufacturer or "—",
            "MPN": part.mpn or "—",
            "Package": part.package or "—",
            "Description": part.description or "—",
            "LCSC #": part.lcsc_number,
            "Datasheet": part.datasheet_url or "—",
        }

        for field, text in field_map.items():
            if field in self._labels:
                # Truncate long descriptions
                if len(text) > 120:
                    text = text[:117] + "..."
                self._labels[field][1].SetLabel(text)

        self.Layout()
        self.GetParent().Layout()

    def show_error(self, message: str) -> None:
        """Display an error message in the panel."""
        self.clear()
        self._title.SetLabel("Error")
        self._labels["Description"][1].SetLabel(message)
        self.Layout()
