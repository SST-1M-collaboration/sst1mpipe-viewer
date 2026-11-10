"""
Pages of the events with an image: DL1 Event and DL2 Event.

Each selected telescope has a camera with a per pixel field of the DL1 image of its event (image,
peak time, cleaning mask), the cleaning mask and the Hillas ellipse, and for the DL2 the
reconstructed source position. The table below lists all the fields of the events.
"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import CheckboxGroup, Div, Select

from ..components import FieldsTable
from ..frames import source_telescope_frame
from .base import LevelRates, Page, event_description, message_div, telescope_header
from .waveforms import field_shapes, set_options

__all__ = ["ImageEventPage"]

#: indices of the display options (check boxes)
SHOW_MASK, SHOW_ELLIPSE, ONLY_RECONSTRUCTED = 0, 1, 2

#: DL1 column which is finite for the events with parameters: in Live mode, the DL1 page can show
#: only these events (not the events without any pixel after the cleaning)
RECONSTRUCTED_COLUMN = "hillas_intensity"


class _TelescopeImage:
    """Camera of the event of a telescope in an image page"""

    def __init__(self, session, tel_id):
        self.header = telescope_header(session, tel_id)
        self.message = message_div(width=330)  # the cameras of the telescopes are side by side
        self.camera = session.camera_panel(geometry=session.geometry(tel_id), title="Image",
                                           on_pixel_click=session.pixel_click(tel_id), width=460, height=430)
        self.layout = column(row(self.header, self.message), self.camera.layout)
        self.shown = False  # an event is displayed

    def show_message(self, text):
        """Show a message above the camera (only sent to the browser if it changed)"""
        if self.message.text != text:
            self.message.text = text


class ImageEventPage(Page):
    """
    The DL1 or DL2 events of the selected telescopes (one camera per telescope, with its color).

    Parameters
    ----------
    session : ViewerSession
        The page of the browser.
    kind : str
        ``"dl1"`` or ``"dl2"``. The camera shows the DL1 image of the event in both cases; the
        DL2 page lists all the DL2 fields of the telescope (every algorithm: energy, classification,
        geometry, impact, disp, with their uncertainties and validity) and, for the DL2 of
        sst1mpipe, shows the reconstructed source position (a star).
    """

    def __init__(self, session, kind="dl1"):
        super().__init__(session)
        self.kind = kind
        self.title = f"{kind.upper()} Event"
        labels = ["Cleaning mask", "Hillas ellipse"]
        if kind == "dl1":
            labels.append("Live: only the events surviving the cleaning")
        self.options = CheckboxGroup(labels=labels, active=list(range(len(labels))), inline=True)
        self.options.on_change("active", lambda attr, old, new: self.refresh())
        self.pixel_field = Select(title="Camera", value="image", options=["image", "peak_time", "image_mask"],
                                  width=200)
        self.pixel_field.on_change("value", lambda attr, old, new: self.refresh())
        self.rates = LevelRates(session, kind)
        self.views = {tel_id: _TelescopeImage(session, tel_id) for tel_id in session.all_tel_ids}
        self.views_container = row()
        self.fields = FieldsTable(width=1000, height=470)
        self._shown_tel_ids = None
        self._source_position = (None, None)  # (tel_id, key), position of the source: the last one
        self.layout = column(
            self.rates.layout,
            row(self.pixel_field, column(Div(text=""), self.options)),
            self.views_container,
            Div(text="<h3 style='margin: 10px 0 0 0'>All the fields of the events</h3>"),
            self.fields.layout,
        )

    def _set_views(self, tel_ids):
        """Cameras of the selected telescopes (the layout changes only when the selection changes)"""
        for tel_id in tel_ids:
            if tel_id not in self.views:  # telescope added after the page was built
                self.views[tel_id] = _TelescopeImage(self.session, tel_id)
        if tel_ids != self._shown_tel_ids:
            self._shown_tel_ids = tel_ids
            self.views_container.children = [self.views[t].layout for t in tel_ids]

    def _events(self, tel_ids):
        """``{tel_id: (key, rows, geometry)}``: the displayed event of each telescope"""
        session = self.session
        only_reconstructed = ONLY_RECONSTRUCTED in self.options.active
        finite_column = RECONSTRUCTED_COLUMN if only_reconstructed else None
        events = {}
        for tel_id in tel_ids:
            key = session.event_key(tel_id, self.kind, finite_column=finite_column)
            rows = self.store.event(tel_id, key, ("dl1", "dl2", "trigger")) if key is not None else {}
            events[tel_id] = (key, rows, session.geometry(tel_id))
        return events

    def refresh(self):
        """Show the displayed event of each selected telescope, and the fields table"""
        session = self.session
        tel_ids = session.tel_ids
        self._set_views(tel_ids)
        self.rates.refresh()
        events = self._events(tel_ids)

        # the menu of the camera: the per pixel fields of the DL1 images
        fields = []
        for _, rows, geometry in events.values():
            if "dl1" in rows and geometry is not None:
                fields += [n for n in field_shapes(rows["dl1"], geometry.n_pixels)["pixel"] if n not in fields]
        set_options(self.pixel_field, fields or ["image", "peak_time", "image_mask"])

        table = {}
        for tel_id, (key, rows, geometry) in events.items():
            view = self.views[tel_id]
            data = rows.get(self.kind)
            if data is not None:
                table[tel_id] = {self.kind: data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})}
            self._show(tel_id, view, key, rows, data, geometry)
        self.fields.set_rows(table)

    def _source(self, tel_id, key, data):
        """Reconstructed source position of a DL2 event in the telescope frame (converted once per event)"""
        if self._source_position[0] != (tel_id, key):
            subarray = self.store.subarray
            frame = subarray.tel[tel_id].camera.geometry.frame if subarray is not None else None
            position = source_telescope_frame(data, frame) if frame is not None else None
            self._source_position = ((tel_id, key), position)
        return self._source_position[1]

    def _show(self, tel_id, view, key, rows, data, geometry):
        """Show the event of a telescope in its camera"""
        session = self.session
        camera = view.camera
        camera.set_caption(event_description(key, rows))
        if geometry is None or data is None:
            if session.follow and view.shown:
                return  # following a stream: the last event displayed is kept
            view.shown = False
            only = ONLY_RECONSTRUCTED in self.options.active and session.follow
            view.show_message(
                "No camera geometry (no subarray)." if geometry is None
                else f"No {self.kind.upper()} data" + (" reconstructed" if only else "")
                + ("" if session.follow else " in this event") + "."
            )
            camera.clear()
            return
        view.shown = True
        image = rows.get("dl1", {})
        name = self.pixel_field.value
        view.show_message("" if name in image else "No DL1 image of this event (its fields are in the table).")
        camera.set_geometry(geometry)
        camera.set_title(name)
        if name in image and np.shape(image[name]) == (geometry.n_pixels,):
            camera.set_image(np.asarray(image[name], dtype=float))
        else:
            camera.clear()
        camera.set_mask(image.get("image_mask") if SHOW_MASK in self.options.active else None)
        # the Hillas parameters are in the DL1 row, and in the DL2 row of sst1mpipe
        hillas = image if "hillas_fov_lon" in image else data
        camera.set_ellipse(hillas if SHOW_ELLIPSE in self.options.active else None)
        if self.kind == "dl2":
            camera.set_source(self._source(tel_id, key, data))
        camera.set_selected(session.selected_pixels(tel_id))
