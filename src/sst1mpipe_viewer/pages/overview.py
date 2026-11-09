"""Overview page: welcome text, telescope array and summary of the data received"""

from bokeh.layouts import column, row
from bokeh.models import CheckboxGroup, ColumnDataSource, DataTable, Div, RadioButtonGroup, TableColumn

from ..components import ArrayMapPanel, ArrayPanel, RatePanel
from ..components.array import earth_locations
from ..store import KINDS
from .base import LEVEL_NAMES, Page, message_div
from .pixel_selection import PixelSelectionPanel

__all__ = ["OverviewPage"]

#: colors of the data levels in the rate plots
LEVEL_COLORS = {"r0": "#1b9e77", "r1": "#d95f02", "dl0": "#7570b3", "dl1": "#e7298a", "dl2": "#66a61e",
                "trigger": "#666666"}

WELCOME = """
<h2 style="margin: 0 0 6px 0">Welcome to the SST-1M event viewer</h2>
<p style="margin: 0 0 4px 0; max-width: 520px">
The viewer shows the events of the telescopes selected here (<b>R0</b>, <b>R1</b>, <b>DL0</b> and
<b>DL1 Event</b> pages) and the statistics accumulated from their DL1 parameters (<b>DL1 Statistics</b>
page), each telescope with its color.
</p>
<ul style="margin: 0; padding-left: 18px; max-width: 520px">
<li><b>Live</b> follows the last event received; <b>&#9664; Prev</b> / <b>Next &#9654;</b> browse the
events; <b>Event id</b> shows an event (an event_id, or <i>#index</i>: #0 the first event, #-1 the last).</li>
<li>A file is processed at once: its first event is shown and the statistics are those of all its events.</li>
<li>Click on a camera pixel to show its waveform (shift+click to select several pixels);
each telescope has its own selection, shared by all the pages.</li>
<li>&#9664; / &#9654; next to a telescope name browse the events of this telescope only.</li>
<li>Select the telescopes with the boxes, or click on a telescope of the array to select or unselect it.</li>
<li>The statistics can be reset globally or plot by plot.</li>
</ul>
"""


class OverviewPage(Page):
    """The array of telescopes, the selection of the telescopes and of the pixels, the data received"""

    title = "Array"

    def __init__(self, session):
        super().__init__(session)
        self._subarray = None
        self.array_panels = {}
        self.message = message_div("No subarray description: the telescope positions are unknown.")
        self.summary_source = ColumnDataSource(data=self._summary({}, {}))
        columns = [
            TableColumn(field="tel_id", title="Telescope", width=70),
            TableColumn(field="type", title="Type", width=150),
            TableColumn(field="position", title="Position (m)", width=140),
        ] + [
            TableColumn(field=kind, title=f"{kind.upper()} events (rate)", width=120) for kind in KINDS
        ] + [TableColumn(field="last_event", title="Last event", width=150)]
        self.summary = DataTable(source=self.summary_source, columns=columns, width=1100, height=110,
                                 index_position=None)
        self.array_container = column(self.message)
        all_tel_ids = session.all_tel_ids
        self.telescopes = CheckboxGroup(labels=[f"TEL {t}" for t in all_tel_ids],
                                        active=[i for i, t in enumerate(all_tel_ids) if t in session.tel_ids],
                                        inline=True)
        self._checkbox_tel_ids = all_tel_ids
        self.telescopes.on_change("active", lambda attr, old, new: self.session.set_tels(
            [self._checkbox_tel_ids[i] for i in new]))
        self.telescope_colors = Div(text=" &nbsp; ".join(
            f"<span style='color: {session.color(t)}; font-weight: bold'>&#9632; TEL {t}</span>" for t in all_tel_ids))
        # rates of each data level in time, one plot per telescope (for the shifter)
        series = {kind: (LEVEL_NAMES[kind], LEVEL_COLORS[kind]) for kind in KINDS}
        self.rate_panels = {}
        for tel_id in all_tel_ids:
            panel = RatePanel(f"Rates of TEL {tel_id}", series, width=1100, height=200)
            panel.figure.title.text_color = session.color(tel_id)
            self.rate_panels[tel_id] = panel
        self.rates_container = column()
        # one pixel selection per telescope (each telescope has its own selection)
        self.pixel_selections = {}
        self.pixel_container = column()
        self._shown_tel_ids = None
        self.layout = column(
            row(column(Div(text=WELCOME, width=540),
                       Div(text="<h3 style='margin: 8px 0 0 0'>Selected telescopes</h3>"),
                       self.telescopes, self.telescope_colors), self.array_container),
            Div(text="<h3 style='margin: 8px 0 0 0'>Data received</h3>"),
            self.summary,
            self.rates_container,
            self.pixel_container,
        )

    def _build_array(self, subarray):
        self._subarray = subarray
        if subarray is None:
            self.array_panels = {}
            self.array_container.children = [self.message]
            return
        # the telescopes on an OpenStreetMap map if the subarray has an Earth location, and in the
        # ground frame (ctapipe ArrayDisplay)
        panels = {}
        colors = {int(t): self.session.color(t) for t in subarray.tel_ids}
        if earth_locations(subarray) is not None:
            panels["Map (OpenStreetMap)"] = ArrayMapPanel(subarray, on_tel_click=self.session.toggle_tel,
                                                          width=560, height=460, colors=colors)
        panels["Ground frame"] = ArrayPanel(subarray, on_tel_click=self.session.toggle_tel, width=560, height=460,
                                            colors=colors)
        self.array_panels = panels
        labels = list(panels)
        view = RadioButtonGroup(labels=labels, active=0)

        def show(attr, old, new):
            for i, panel in enumerate(panels.values()):
                panel.layout.visible = i == new

        view.on_change("active", show)
        show(None, None, 0)
        self.array_container.children = ([view] if len(labels) > 1 else []) + [p.layout for p in panels.values()]

    def _summary(self, counts, rates):
        store = self.store
        tel_ids = store.tel_ids
        subarray = store.subarray
        data = {key: [] for key in ("tel_id", "type", "position", *KINDS, "last_event")}
        for tel_id in tel_ids:
            data["tel_id"].append(f"TEL {tel_id}")
            if subarray is not None and tel_id in subarray.tel:
                data["type"].append(str(subarray.tel[tel_id]))
                x, y, z = subarray.positions[tel_id].to_value("m")
                data["position"].append(f"({x:.1f}, {y:.1f}, {z:.1f})")
            else:
                data["type"].append("unknown")
                data["position"].append("")
            for kind in KINDS:
                n = counts.get((tel_id, kind), 0)
                rate = rates.get((tel_id, kind), 0.0)
                data[kind].append(f"{n} ({rate:.1f} Hz)" if n else "–")
            key = store.latest_key(tel_id)
            data["last_event"].append("–" if key is None else f"{key[0]} / {key[1]}")
        return data

    def refresh(self):
        if self.store.subarray is not self._subarray:
            self._build_array(self.store.subarray)
        rates = self.store.rates()
        self.summary_source.data = self._summary(self.store.counts(), rates)
        selected_tels = self.session.tel_ids
        for tel_id in selected_tels:
            if tel_id not in self.pixel_selections:
                self.pixel_selections[tel_id] = PixelSelectionPanel(self.session, tel_id)
        if selected_tels != self._shown_tel_ids:
            self._shown_tel_ids = selected_tels
            self.pixel_container.children = [self.pixel_selections[t].layout for t in selected_tels]
            self.rates_container.children = [self.rate_panels[t].layout for t in selected_tels
                                             if t in self.rate_panels]
        for tel_id in selected_tels:
            if tel_id in self.rate_panels:
                self.rate_panels[tel_id].update({kind: self.store.rate_history(tel_id, kind) for kind in KINDS})
        for tel_id in selected_tels:
            self.pixel_selections[tel_id].refresh()
        active = sorted({tel for (tel, _), rate in rates.items() if rate > 0})
        selected = self.session.tel_ids
        active_boxes = [i for i, t in enumerate(self._checkbox_tel_ids) if t in selected]
        if self.telescopes.active != active_boxes:
            self.telescopes.active = active_boxes
        for panel in self.array_panels.values():
            panel.set_selected(selected)
            panel.set_active(active)
