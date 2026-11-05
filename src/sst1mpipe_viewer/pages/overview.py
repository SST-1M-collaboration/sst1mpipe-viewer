"""Overview page: welcome text, telescope array and summary of the data received"""

from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, DataTable, Div, TableColumn

from ..components import ArrayPanel
from ..store import KINDS
from .base import Page, message_div

__all__ = ["OverviewPage"]

WELCOME = """
<h2 style="margin: 0 0 6px 0">Welcome to the SST-1M event viewer</h2>
<p style="margin: 0 0 4px 0; max-width: 520px">
The viewer shows the last events received for the telescope chosen at the top of the page
(<b>R0</b>, <b>R1</b>, <b>DL0</b> and <b>DL1 Event</b> pages) and the statistics accumulated
from the DL1 parameters (<b>DL1 Statistics</b> page).
</p>
<ul style="margin: 0; padding-left: 18px; max-width: 520px">
<li><b>Live</b> follows the last event; <b>&#9664; Prev</b> / <b>Next &#9654;</b> browse the last events received.</li>
<li>Click on a camera pixel to show its waveform (shift+click to select several pixels);
the selection is shared by all the pages.</li>
<li>Click on a telescope of the array to select it.</li>
<li>The statistics can be reset globally or plot by plot.</li>
</ul>
"""


class OverviewPage(Page):
    title = "Overview"

    def __init__(self, session):
        super().__init__(session)
        self._subarray = None
        self.array_panel = None
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
        self.layout = column(
            row(Div(text=WELCOME, width=540), self.array_container),
            Div(text="<h3 style='margin: 8px 0 0 0'>Data received</h3>"),
            self.summary,
        )

    def _build_array(self, subarray):
        self._subarray = subarray
        if subarray is None:
            self.array_panel = None
            self.array_container.children = [self.message]
            return
        self.array_panel = ArrayPanel(subarray, on_tel_click=self.session.set_tel, width=560, height=460)
        self.array_container.children = [self.array_panel.layout]

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
        if self.array_panel is not None:
            self.array_panel.set_selected(self.session.tel_id)
            self.array_panel.set_active(sorted({tel for (tel, _), rate in rates.items() if rate > 0}))
