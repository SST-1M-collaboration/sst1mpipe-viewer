"""Selection of the pixels by groups of the camera (trigger patches, modules, FADC boards, sectors, ...)"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Button, Div, Select, TextInput

from ..components import CameraPanel
from ..pixel_groups import GROUPINGS, parse_ids, pixel_groups

__all__ = ["PixelSelectionPanel"]

HELP = """
<p style="margin: 0; max-width: 300px">
Choose how the pixels are grouped, then click on the camera to select the pixels of a group
(shift+click adds or removes a group), or enter the ids of groups (e.g. <i>0, 3-5</i>).
The selection is shared by all the pages (waveforms, cameras).
</p>
"""


def _colors(group_ids):
    """Values spreading the colors of neighbouring groups (consecutive ids) over the colormap"""
    return (np.asarray(group_ids, dtype=float) * 0.6180339887) % 1.0


class PixelSelectionPanel:
    """Camera colored by group of pixels: a click selects all the pixels of a group"""

    def __init__(self, session):
        self.session = session
        self.groups = pixel_groups()
        self.grouping = Select(title="Select pixels by", value="Module", options=list(GROUPINGS), width=170)
        self.grouping.on_change("value", lambda attr, old, new: self.refresh(force=True))
        self.ids = TextInput(title="Ids of the groups", placeholder="e.g. 0, 3-5", width=170)
        self.ids.on_change("value", lambda attr, old, new: self.select_ids(new))
        self.add = Button(label="Add to the selection", width=170)
        self.add.on_click(lambda: self.select_ids(self.ids.value, add=True))
        self.info = Div(text="", width=300)
        self.message = Div(text="", width=300, styles={"color": "#666"})
        self.camera = CameraPanel(title="Groups of pixels", width=430, height=400, cmap="viridis",
                                  show_controls=False, on_pixel_tap=self.tapped, show_colorbar=False,
                                  selected_color="#e53935")
        self._state = None
        self._info_state = None
        self.layout = row(
            column(Div(text="<h3 style='margin: 8px 0 0 0'>Pixel selection</h3>"), Div(text=HELP),
                   self.grouping, self.ids, self.add, self.info, self.message),
            self.camera.layout,
        )

    @property
    def column(self):
        return GROUPINGS[self.grouping.value]

    def _geometry(self):
        geometry = self.session.geometry()
        return geometry if self.groups.matches(geometry) else None

    def tapped(self, pixel, shift):
        """Select the group of the clicked pixel (shift: add or remove the group)"""
        geometry = self._geometry()
        if geometry is None:
            return
        group = self.groups.group_of(geometry, self.column, pixel)
        pixels = self.groups.pixels(geometry, self.column, [group])
        selected = list(self.session.selected_pixels)
        if not shift:
            selected = pixels
        elif set(pixels) <= set(selected):
            selected = [p for p in selected if p not in set(pixels)]
        else:
            selected = sorted(set(selected) | set(pixels))
        self.session.set_selected_pixels(selected)

    def select_ids(self, text, add=False):
        """Select the pixels of the groups whose ids are in ``text``"""
        geometry = self._geometry()
        if geometry is None or not text.strip():
            return
        try:
            ids = parse_ids(text)
        except ValueError as error:
            self.message.text = str(error)
            return
        pixels = self.groups.pixels(geometry, self.column, ids)
        known = set(self.groups.values(geometry, self.column).tolist())
        unknown = [i for i in ids if i not in known]
        self.message.text = f"Unknown {self.grouping.value.lower()} ids: {unknown}" if unknown else ""
        if not pixels:
            # only unknown ids: the selection is kept
            return
        if add:
            pixels = sorted(set(self.session.selected_pixels) | set(pixels))
        self.session.set_selected_pixels(pixels)

    def refresh(self, force=False):
        geometry = self._geometry()
        if geometry is None:
            self.camera.layout.visible = False
            self.info.text = ""
            self.message.text = "The pixel groups are those of DigiCam: not available for this camera."
            return
        self.camera.layout.visible = True
        if self.message.text.startswith("The pixel groups"):
            self.message.text = ""
        state = (self.session.tel_id, self.column)
        values = self.groups.values(geometry, self.column)
        if force or state != self._state:
            self._state = state
            self.camera.set_geometry(geometry)
            self.camera.set_image(_colors(values))
            self.camera.set_hover_column(self.grouping.value, values)
            self.camera.set_title(f"{self.grouping.value}s of TEL {self.session.tel_id}"
                                  f" ({len(np.unique(values))} groups)")
        selected = self.session.selected_pixels
        self.camera.set_selected(selected)
        info_state = (state, tuple(selected))
        if info_state == self._info_state:
            return
        self._info_state = info_state
        if selected:
            groups = self.groups.groups(geometry, self.column, selected)
            complete = [g for g in groups if set(self.groups.pixels(geometry, self.column, [g])) <= set(selected)]
            shown = ", ".join(str(g) for g in complete[:20]) + (" ..." if len(complete) > 20 else "")
            self.info.text = (f"<b>{len(selected)} pixels selected</b><br>"
                              f"complete {self.grouping.value.lower()}s: {shown or 'none'}")
        else:
            self.info.text = "<b>No pixel selected</b>"
