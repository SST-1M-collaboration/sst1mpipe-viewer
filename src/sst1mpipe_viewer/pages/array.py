"""
Array page: welcome text, telescope positions (map; a click on a telescope selects or unselects
it), rates of the data levels of each selected telescope. The telescopes and the pixels are
selected in the Selection page (`sst1mpipe_viewer.pages.selection`).
"""

from bokeh.layouts import column, row
from bokeh.models import Div, RadioButtonGroup

from .. import style
from ..components import ArrayMapPanel, ArrayPanel, RatePanel
from ..components.array import earth_locations
from ..store import TELESCOPE_KINDS as KINDS
from .base import LEVEL_NAMES, Page, message_div

__all__ = ["ArrayPage"]

#: colors of the data levels in the rate plots
LEVEL_COLORS = {"r0": "#1b9e77", "r1": "#d95f02", "dl0": "#7570b3", "dl1": "#e7298a", "dl2": "#66a61e",
                "trigger": "#bdbdbd"}

WELCOME = """
<h2 style="margin: 0 0 6px 0">Welcome to the SST-1M event viewer</h2>
<p style="margin: 0 0 4px 0; max-width: 520px">
The viewer shows the events of the selected telescopes (<b>R0</b>, <b>R1</b>, <b>DL0</b>,
<b>DL1 Event</b> and <b>DL2 Event</b> pages), the statistics accumulated from their parameters
(<b>Statistics</b> pages), the stereo reconstruction (<b>DL2 Stereo</b>), the gamma-ray candidates
(<b>DL3</b>) and the rates of the data, each telescope with its color.
</p>
<ul style="margin: 0; padding-left: 18px; max-width: 520px">
<li>The telescopes and the pixels are selected in the <b>Selection</b> page (a click on a telescope
of the map also selects or unselects it).</li>
<li><b>Live</b> follows the last valid events; <b>&#9664; Prev</b> / <b>Next &#9654;</b> browse the
events; <b>Event id</b> shows an event (an event_id, or <i>#index</i>: #0 the first event, #-1 the last).</li>
<li>&#9664; / &#9654; next to a telescope name browse the events of this telescope only.</li>
<li>A file is processed at once: its first event is shown and the statistics are those of all its events.</li>
<li>The statistics can be reset for all the telescopes, the selected ones, or plot by plot.</li>
</ul>
"""


class ArrayPage(Page):
    """The array of telescopes and the rates of the data levels of the selected telescopes"""

    title = "Array"

    def __init__(self, session):
        super().__init__(session)
        self._subarray = None
        self.array_panels = {}
        self.message = message_div("No subarray description: the telescope positions are unknown.")
        self.array_container = column(self.message)
        all_tel_ids = session.all_tel_ids
        # rates of each data level in time, one plot per telescope (for the shifter)
        series = {kind: (LEVEL_NAMES[kind], LEVEL_COLORS[kind]) for kind in KINDS}
        self.rate_panels = {}
        for tel_id in all_tel_ids:
            panel = RatePanel(f"Rates of TEL {tel_id} per minute (dashed line: displayed event)", series,
                              markers={"event": style.FOREGROUND}, width=1100, height=200)
            panel.figure.title.text_color = session.color(tel_id)
            self.rate_panels[tel_id] = panel
        self.rates_container = column()
        self._shown_tel_ids = None
        self.layout = column(
            row(Div(text=WELCOME, width=540), self.array_container),
            Div(text="<h3 style='margin: 8px 0 0 0'>Rates of the valid events</h3>"),
            self.rates_container,
        )

    def _build_array(self, subarray):
        """Plots of the telescope positions (map and ground frame) of a subarray"""
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
            """Show the plot chosen with the buttons"""
            for i, panel in enumerate(panels.values()):
                panel.layout.visible = i == new

        view.on_change("active", show)
        show(None, None, 0)
        self.array_container.children = ([view] if len(labels) > 1 else []) + [p.layout for p in panels.values()]

    def refresh(self):
        """Update the rates and the selected telescopes of the map"""
        if self.store.subarray is not self._subarray:
            self._build_array(self.store.subarray)
        rates = self.store.rates()  # rows received in the last seconds: the telescopes receiving data
        selected_tels = self.session.tel_ids
        if selected_tels != self._shown_tel_ids:
            self._shown_tel_ids = selected_tels
            self.rates_container.children = [self.rate_panels[t].layout for t in selected_tels
                                             if t in self.rate_panels]
        for tel_id in selected_tels:
            if tel_id in self.rate_panels:
                self.rate_panels[tel_id].update({kind: self.store.rate_history(tel_id, kind) for kind in KINDS})
                event_time = self.store.event_time(tel_id, self.session.event_key(tel_id))
                self.rate_panels[tel_id].set_markers({"event": event_time})
        active = sorted({tel for (tel, _), rate in rates.items() if rate > 0})
        selected = self.session.tel_ids
        for panel in self.array_panels.values():
            panel.set_selected(selected)
            panel.set_active(active)
