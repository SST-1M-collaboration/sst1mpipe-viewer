"""DL1 pages: the image of an event and the accumulated statistics of the DL1 parameters"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Button, CheckboxGroup, ColumnDataSource, DataTable, Div, Select, TableColumn, TextInput

from ..components import FieldsTable, Histogram1DPanel, Histogram2DPanel
from ..config import display_options
from ..units import column_unit
from .base import Page, event_description, message_div, telescope_header
from .waveforms import field_shapes, set_options

__all__ = ["DL1EventPage", "DL1StatisticsPage"]

SHOW_MASK, SHOW_ELLIPSE, ONLY_CLEANED = 0, 1, 2


class _TelescopeImage:
    """Camera of the DL1 event of a telescope"""

    def __init__(self, session, tel_id):
        self.header = telescope_header(session, tel_id)
        self.message = message_div()
        self.camera = session.camera_panel(title="Image", on_pixel_click=session.pixel_click(tel_id), width=460,
                                           height=430)
        self.layout = column(row(self.header, self.message), self.camera.layout)
        self.shown = False

    def show_message(self, text):
        if self.message.text != text:
            self.message.text = text


class DL1EventPage(Page):
    """
    The DL1 events of the selected telescopes (one camera per telescope, with its color): a per
    pixel field chosen in a menu (image, peak time, ...), the cleaning mask and the Hillas
    ellipse; the table has all the fields of the events.
    """

    title = "DL1 Event"

    def __init__(self, session):
        super().__init__(session)
        self.options = CheckboxGroup(
            labels=["Cleaning mask", "Hillas ellipse", "Live: only the events surviving the cleaning"],
            active=[SHOW_MASK, SHOW_ELLIPSE, ONLY_CLEANED], inline=True,
        )
        self.options.on_change("active", lambda attr, old, new: self.refresh())
        self.pixel_field = Select(title="Camera", value="image", options=["image", "peak_time", "image_mask"],
                                  width=200)
        self.pixel_field.on_change("value", lambda attr, old, new: self.refresh())
        self.views = {tel_id: _TelescopeImage(session, tel_id) for tel_id in session.all_tel_ids}
        self.views_container = row()
        self.fields = FieldsTable(width=1000, height=470)
        self._shown_tel_ids = None
        self.layout = column(
            row(self.pixel_field, column(Div(text=""), self.options)),
            self.views_container,
            Div(text="<h3 style='margin: 10px 0 0 0'>All the fields of the events</h3>"),
            self.fields.layout,
        )

    def refresh(self):
        session = self.session
        tel_ids = session.tel_ids
        for tel_id in tel_ids:
            if tel_id not in self.views:
                self.views[tel_id] = _TelescopeImage(session, tel_id)
        if tel_ids != self._shown_tel_ids:
            self._shown_tel_ids = tel_ids
            self.views_container.children = [self.views[t].layout for t in tel_ids]
        only_cleaned = ONLY_CLEANED in self.options.active
        show_mask = SHOW_MASK in self.options.active
        show_ellipse = SHOW_ELLIPSE in self.options.active
        events = {}
        for tel_id in tel_ids:
            geometry = session.geometry(tel_id)
            key = session.event_key(tel_id, "dl1", finite_column="hillas_intensity" if only_cleaned else None)
            rows = self.store.event(tel_id, key) if key is not None else {}
            events[tel_id] = (key, rows, rows.get("dl1"), geometry)

        fields = []
        for _, _, data, geometry in events.values():
            if data is not None and geometry is not None:
                fields += [n for n in field_shapes(data, geometry.n_pixels)["pixel"] if n not in fields]
        set_options(self.pixel_field, fields or ["image", "peak_time", "image_mask"])

        table = {}
        for tel_id, (key, rows, data, geometry) in events.items():
            view = self.views[tel_id]
            camera = view.camera
            camera.set_caption(event_description(key, rows))
            if geometry is None or data is None:
                if session.follow and view.shown:
                    continue  # following a stream: the last event displayed is kept
                view.shown = False
                view.show_message(
                    "No camera geometry (no subarray)." if geometry is None
                    else "No DL1 data" + (" surviving the cleaning" if session.follow and only_cleaned else "")
                    + ("" if session.follow else " in this event") + "."
                )
                camera.clear()
                continue
            view.shown = True
            view.show_message("")
            camera.set_geometry(geometry)
            name = self.pixel_field.value
            camera.set_title(name)
            if name in data and np.shape(data[name]) == (geometry.n_pixels,):
                camera.set_image(np.asarray(data[name], dtype=float))
            else:
                camera.clear()
            camera.set_mask(data.get("image_mask") if show_mask else None)
            camera.set_ellipse(data if show_ellipse else None)
            camera.set_selected(session.selected_pixels(tel_id))
            table[tel_id] = {"dl1": data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})}
        self.fields.set_rows(table)


def _label(name, transform=None, unit=None):
    unit = column_unit(name) if unit is None else unit
    if transform:
        return f"{transform}({name})"
    return f"{name} ({unit})" if unit else name


class DL1StatisticsPage(Page):
    """
    Accumulated histograms of the DL1 parameters of the selected telescopes (superimposed, with
    the color of each telescope), their correlations and camera maps (one column per telescope)
    """

    title = "DL1 Statistics"

    def __init__(self, session):
        super().__init__(session)
        config = self.store.statistics_config
        options = display_options(config)
        reset = self._reset_one
        all_tel_ids = session.all_tel_ids
        colors = {tel_id: session.color(tel_id) for tel_id in all_tel_ids}

        self.hist1d = [
            Histogram1DPanel(
                spec.get("name", spec["column"]), title=spec.get("title", spec["column"]),
                x_label=_label(spec["column"], spec.get("transform"), spec.get("unit")),
                log_y=options[spec.get("name", spec["column"])]["log_y"], on_reset=reset, colors=colors,
            )
            for spec in config.get("hist1d", ())
        ]
        # 2D histograms and camera maps: one per telescope
        self.hist2d = {}
        for spec in config.get("hist2d", ()):
            name = spec.get("name", f"{spec['y']}_vs_{spec['x']}")
            for tel_id in all_tel_ids:
                panel = Histogram2DPanel(
                    name, title=f"{spec.get('title') or name} – TEL {tel_id}",
                    x_label=_label(spec["x"], spec.get("x_transform")),
                    y_label=_label(spec["y"], spec.get("y_transform")), on_reset=reset,
                )
                panel.figure.title.text_color = colors[tel_id]
                self.hist2d[(name, tel_id)] = panel
        self._hist2d_names = list(dict.fromkeys(name for name, _ in self.hist2d))
        maps = {spec.get("name", f"{spec['column']}_{spec.get('mode', 'mean')}"): spec.get("title", spec["column"])
                for spec in config.get("camera", ())}
        self.map_titles = maps
        self.camera_map = Select(title="Camera map", value=next(iter(maps), ""), options=list(maps), width=420)
        self.camera_map.on_change("value", lambda attr, old, new: self._refresh_maps(force=True))
        self.maps = {}
        for tel_id in all_tel_ids:
            panel = session.camera_panel(title="", on_pixel_click=session.pixel_click(tel_id), width=420,
                                         height=380)
            panel.figure.title.text_color = colors[tel_id]
            self.maps[tel_id] = panel
        self._map_states = {}

        # a table, not a Div: changing a Div lays out the whole page again (slow)
        self.counters_source = ColumnDataSource(data=dict(tel=[], rows=[], selected=[], without=[], cuts=[]))
        self.counters = DataTable(source=self.counters_source, index_position=None, width=900, height=80, columns=[
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
        self.reset_tel = Button(label="Reset selected telescopes", width=190, button_type="warning")
        self.reset_tel.on_click(lambda: self._reset_selected())
        self.reset_all = Button(label="Reset all telescopes", width=150, button_type="danger")
        self.reset_all.on_click(lambda: self._reset())
        self.error = Div(text="", styles={"color": "#c62828"})
        self.legend = Div(text="", height=24)
        self.correlations = column()
        self.maps_row = row()
        self._shown_tel_ids = None

        def grid(panels, n_columns):
            return column([row(panels[i:i + n_columns]) for i in range(0, len(panels), n_columns)])

        def section(title):
            return Div(text=f"<h3 style='margin: 10px 0 0 0'>{title}</h3>")

        self.layout = column(
            row(self.cuts, column(Div(text=""), row(self.apply_cuts, self.reset_tel, self.reset_all))),
            self.error,
            self.counters,
            self.legend,
            section("Parameter distributions"),
            grid([p.layout for p in self.hist1d], 4),
            section("Correlations"),
            self.correlations,
            section("Camera maps"),
            self.camera_map,
            self.maps_row,
        )

    def _reset(self, tel_id=None, name=None):
        self.store.reset_statistics(tel_id, name)
        self.session.request_refresh()

    def _reset_selected(self, name=None):
        for tel_id in self.session.tel_ids:
            self.store.reset_statistics(tel_id, name)
        self.session.request_refresh()

    def _reset_one(self, name):
        self._reset_selected(name)

    def _apply_cuts(self):
        cuts = [c.strip() for c in self.cuts.value.split(";") if c.strip()]
        try:
            self.store.set_cuts(cuts)
        except ValueError as error:
            self.error.text = str(error)
            return
        self.error.text = ""
        self.session.request_refresh()

    def _set_layout(self, tel_ids):
        """Columns of the selected telescopes (changed only when the selection changes)"""
        if tel_ids == self._shown_tel_ids:
            return
        self._shown_tel_ids = tel_ids
        session = self.session
        self.legend.text = "Telescopes: " + " &nbsp; ".join(
            f"<span style='color: {session.color(t)}; font-weight: bold'>&#9632; TEL {t}</span>" for t in tel_ids)
        self.correlations.children = [
            row([self.hist2d[(name, t)].layout for t in tel_ids if (name, t) in self.hist2d])
            for name in self._hist2d_names
        ]
        self.maps_row.children = [self.maps[t].layout for t in tel_ids if t in self.maps]
        for panel in self.hist1d:
            panel.invalidate()

    def refresh(self):
        session = self.session
        tel_ids = [t for t in session.tel_ids if t in self.maps]
        self._set_layout(tel_ids)
        snapshots = {tel_id: self.store.statistics(tel_id) for tel_id in tel_ids}
        self._snapshots = snapshots
        self.counters_source.data = dict(
            tel=[f"TEL {t}" for t in tel_ids], rows=[s["n_rows"] for s in snapshots.values()],
            selected=[s["n_selected"] for s in snapshots.values()],
            without=[s["n_without_cut_columns"] for s in snapshots.values()],
            cuts=[" AND ".join(s["cuts"]) or "none" for s in snapshots.values()],
        )
        for panel in self.hist1d:
            panel.update({t: s["accumulators"][panel.name] for t, s in snapshots.items()
                          if panel.name in s["accumulators"]})
        for tel_id, snapshot in snapshots.items():
            for name in self._hist2d_names:
                if name in snapshot["accumulators"]:
                    self.hist2d[(name, tel_id)].update(snapshot["accumulators"][name])
        self._refresh_maps()

    def _refresh_maps(self, force=False):
        session = self.session
        name = self.camera_map.value
        for tel_id, snapshot in getattr(self, "_snapshots", {}).items():
            panel = self.maps[tel_id]
            geometry = session.geometry(tel_id)
            accumulator = snapshot["accumulators"].get(name)
            if geometry is None or accumulator is None or len(accumulator["values"]) != geometry.n_pixels:
                continue
            state = (name, accumulator["n_entries"])
            if force or state != self._map_states.get(tel_id):
                self._map_states[tel_id] = state
                panel.set_geometry(geometry)
                panel.set_image(accumulator["values"])
                panel.set_title(f"{self.map_titles.get(name, name)} – TEL {tel_id}")
                panel.set_caption(f"N={accumulator['n_entries']}")
            panel.set_selected(session.selected_pixels(tel_id))
