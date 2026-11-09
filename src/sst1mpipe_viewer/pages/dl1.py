"""DL1 pages: the image of an event and the accumulated statistics of the DL1 parameters"""

import numpy as np
from bokeh.layouts import Spacer, column, row
from bokeh.models import Button, CheckboxGroup, ColumnDataSource, DataTable, Div, TableColumn, TextInput

from ..components import CameraPanel, FieldsTable, Histogram1DPanel, Histogram2DPanel
from ..config import display_options
from ..units import column_unit
from .base import Page, event_description, message_div

__all__ = ["DL1EventPage", "DL1StatisticsPage"]

SHOW_MASK, SHOW_ELLIPSE, ONLY_CLEANED = 0, 1, 2


class DL1EventPage(Page):
    """Image and peak time of an event, with its cleaning mask, Hillas ellipse and parameters"""

    title = "DL1 Event"

    def __init__(self, session):
        super().__init__(session)
        self.message = message_div()
        self.options = CheckboxGroup(
            labels=["Cleaning mask", "Hillas ellipse", "Live: only the events surviving the cleaning"],
            active=[SHOW_MASK, SHOW_ELLIPSE, ONLY_CLEANED], inline=True,
        )
        self.options.on_change("active", lambda attr, old, new: self.refresh())
        self.image = CameraPanel(title="Image", on_pixel_click=session.set_selected_pixels)
        self.peak_time = CameraPanel(title="Peak time", cmap="viridis", on_pixel_click=session.set_selected_pixels)
        self.parameters = FieldsTable(width=460, height=470)
        self.layout = column(
            self.message,
            self.options,
            row(self.image.layout, self.peak_time.layout, self.parameters.layout),
        )

    def refresh(self):
        session = self.session
        geometry = session.geometry()
        only_cleaned = ONLY_CLEANED in self.options.active
        key = session.event_key("dl1", finite_column="hillas_intensity" if only_cleaned else None)
        rows = self.store.event(session.tel_id, key) if key is not None else {}
        data = rows.get("dl1")
        self.image.set_caption(event_description(key, rows))
        if geometry is None or data is None:
            self.message.text = (
                "No camera geometry for this telescope (no subarray)." if geometry is None
                else f"No DL1 data for TEL {session.tel_id}"
                + (" surviving the cleaning" if session.follow and only_cleaned else "")
                + ("" if session.follow else " in this event") + "."
            )
            self.message.visible = True
            self.image.clear()
            self.peak_time.clear()
            self.parameters.set_rows({})
            return
        self.message.visible = False
        show_mask = SHOW_MASK in self.options.active
        show_ellipse = SHOW_ELLIPSE in self.options.active
        mask = data.get("image_mask") if show_mask else None
        hillas = data if show_ellipse else None
        for panel, name in ((self.image, "image"), (self.peak_time, "peak_time")):
            panel.set_geometry(geometry)
            panel.set_title(f"{name.replace('_', ' ').capitalize()} – TEL {session.tel_id}")
            if name in data and np.shape(data[name]) == (geometry.n_pixels,):
                panel.set_image(data[name])
            else:
                panel.clear()
            panel.set_mask(mask)
            panel.set_ellipse(hillas)
            panel.set_selected(session.selected_pixels)
        self.parameters.set_rows({"dl1": data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})})


def _label(name, transform=None, unit=None):
    unit = column_unit(name) if unit is None else unit
    if transform:
        return f"{transform}({name})"
    return f"{name} ({unit})" if unit else name


class DL1StatisticsPage(Page):
    """Accumulated histograms and camera maps of the DL1 data of the selected telescope"""

    title = "DL1 Statistics"

    def __init__(self, session):
        super().__init__(session)
        config = self.store.statistics_config
        options = display_options(config)
        reset = self._reset_one

        self.hist1d = [
            Histogram1DPanel(
                spec.get("name", spec["column"]), title=spec.get("title", spec["column"]),
                x_label=_label(spec["column"], spec.get("transform"), spec.get("unit")),
                log_y=options[spec.get("name", spec["column"])]["log_y"], on_reset=reset,
            )
            for spec in config.get("hist1d", ())
        ]
        self.hist2d = [
            Histogram2DPanel(
                spec.get("name", f"{spec['y']}_vs_{spec['x']}"), title=spec.get("title"),
                x_label=_label(spec["x"], spec.get("x_transform")), y_label=_label(spec["y"], spec.get("y_transform")),
                on_reset=reset,
            )
            for spec in config.get("hist2d", ())
        ]
        self.cameras = []
        self._camera_states = {}
        self._tel_id = None
        for spec in config.get("camera", ()):
            name = spec.get("name", f"{spec['column']}_{spec.get('mode', 'mean')}")
            panel = CameraPanel(title=spec.get("title", name), width=420, height=380,
                                on_pixel_click=session.set_selected_pixels)
            reset_button = Button(label="Reset", width=60, height=26, button_type="light")
            reset_button.on_click(lambda name=name: reset(name))
            self.cameras.append((name, panel, column(panel.layout, row(Spacer(width=350), reset_button))))

        # a table, not a Div: changing a Div lays out the whole page again (slow)
        self.counters_source = ColumnDataSource(data=dict(tel=[], rows=[], selected=[], without=[], cuts=[]))
        self.counters = DataTable(source=self.counters_source, index_position=None, width=900, height=55, columns=[
            TableColumn(field="tel", title="Telescope", width=80),
            TableColumn(field="rows", title="DL1 rows accumulated", width=150),
            TableColumn(field="selected", title="Passing the cuts", width=130),
            TableColumn(field="without", title="Without the cut columns", width=170),
            TableColumn(field="cuts", title="Cuts", width=370),
        ])
        self.cuts = TextInput(
            title="Cuts, separated by ';' (e.g. hillas_intensity > 50; leakage_intensity_width_2 < 0.2)",
            value="; ".join(config.get("cuts", ())), width=560,
        )
        self.apply_cuts = Button(label="Apply cuts (resets)", width=150, button_type="primary")
        self.apply_cuts.on_click(self._apply_cuts)
        self.reset_tel = Button(label="Reset telescope", width=130, button_type="warning")
        self.reset_tel.on_click(lambda: self._reset(self.session.tel_id))
        self.reset_all = Button(label="Reset all telescopes", width=150, button_type="danger")
        self.reset_all.on_click(lambda: self._reset())
        self.error = Div(text="", styles={"color": "#c62828"})
        self.message = message_div()

        def grid(panels, n_columns):
            return column([row(panels[i:i + n_columns]) for i in range(0, len(panels), n_columns)])

        def section(title):
            return Div(text=f"<h3 style='margin: 10px 0 0 0'>{title}</h3>")

        self.layout = column(
            row(self.cuts, column(Div(text=""), row(self.apply_cuts, self.reset_tel, self.reset_all))),
            self.error,
            self.counters,
            self.message,
            section("Parameter distributions"),
            grid([p.layout for p in self.hist1d], 4),
            section("Correlations"),
            grid([p.layout for p in self.hist2d], 3),
            section("Camera maps"),
            grid([c[2] for c in self.cameras], 3),
        )

    def _reset(self, tel_id=None, name=None):
        self.store.reset_statistics(tel_id, name)
        self.session.request_refresh()

    def _reset_one(self, name):
        self._reset(self.session.tel_id, name)

    def _apply_cuts(self):
        cuts = [c.strip() for c in self.cuts.value.split(";") if c.strip()]
        try:
            self.store.set_cuts(cuts)
        except ValueError as error:
            self.error.text = str(error)
            return
        self.error.text = ""
        self.session.request_refresh()

    def refresh(self):
        session = self.session
        if session.tel_id is None:
            return
        if session.tel_id != self._tel_id:
            # the panels skip the snapshots which did not change: force them for a new telescope
            self._tel_id = session.tel_id
            for panel in (*self.hist1d, *self.hist2d):
                panel.invalidate()
        snapshot = self.store.statistics(session.tel_id)
        accumulators = snapshot["accumulators"]
        self.counters_source.data = dict(
            tel=[f"TEL {session.tel_id}"], rows=[snapshot["n_rows"]], selected=[snapshot["n_selected"]],
            without=[snapshot["n_without_cut_columns"]], cuts=[" AND ".join(snapshot["cuts"]) or "none"],
        )
        for panel in (*self.hist1d, *self.hist2d):
            if panel.name in accumulators:
                panel.update(accumulators[panel.name])
        geometry = session.geometry()
        message = "" if geometry is not None else "No camera geometry: the camera maps are not shown."
        if self.message.text != message:
            self.message.text = message
        for name, panel, _ in self.cameras:
            if geometry is None or name not in accumulators:
                continue
            values = accumulators[name]["values"]
            if len(values) != geometry.n_pixels:
                continue
            state = (session.tel_id, accumulators[name]["n_entries"])
            if state != self._camera_states.get(name):
                self._camera_states[name] = state
                panel.set_geometry(geometry)
                panel.set_image(values)
                panel.set_caption(f"N={accumulators[name]['n_entries']}")
            panel.set_selected(session.selected_pixels)
