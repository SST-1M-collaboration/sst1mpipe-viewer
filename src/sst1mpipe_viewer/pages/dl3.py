"""
DL3 page: the gamma-ray candidates of the observations (`sst1mpipe_viewer.dl3`).

Unlike the other pages, the DL3 are not per telescope: the page shows the observations received,
the rate of their events in time and the accumulated histograms (energy, theta^2 to the target,
sky map around the target, position in the field of view).
"""

from astropy.time import Time
from bokeh.layouts import column, row
from bokeh.models import Button, ColumnDataSource, DataTable, Div, TableColumn

from ..components import Histogram1DPanel, Histogram2DPanel, RatePanel
from ..components.histogram import format_number
from ..config import display_options
from .base import Page
from .statistics import axis_label

__all__ = ["DL3Page"]

#: color of the DL3 plots (the DL3 are not per telescope)
COLOR = "#7b3294"
#: key of the single series of the plots
ALL = "all"


def _position(position):
    """Text of a sky position (ra, dec) in deg"""
    return "–" if position is None else f"{position[0]:.3f}, {position[1]:.3f}"


def _time(unix):
    """ISO date of a unix time, '–' if unknown"""
    return Time(unix, format="unix").isot[:19] if unix == unix else "–"


class DL3Page(Page):
    """The DL3 events of all the observations: observations table, rate in time, histograms"""

    title = "DL3"

    def __init__(self, session):
        super().__init__(session)
        config = self.store.dl3.config
        options = display_options(config)
        self.observations_source = ColumnDataSource(data=self._observations([]))
        self.observations = DataTable(source=self.observations_source, index_position=None, width=1100, height=90,
                                      columns=[
            TableColumn(field="obs_id", title="Observation", width=110),
            TableColumn(field="object", title="Object", width=110),
            TableColumn(field="target", title="Target RA, Dec (deg)", width=150),
            TableColumn(field="pointing", title="Pointing RA, Dec (deg)", width=150),
            TableColumn(field="n_events", title="Events", width=80),
            TableColumn(field="livetime", title="Livetime (s)", width=90),
            TableColumn(field="rate", title="Events / livetime (Hz)", width=140),
            TableColumn(field="start", title="First event", width=150),
            TableColumn(field="stop", title="Last event", width=150),
        ])
        self.rates = RatePanel("Rate of the DL3 events", {ALL: ("DL3 events", COLOR)}, width=1100, height=220)
        self.hist1d = [
            Histogram1DPanel(
                spec.get("name", spec["column"]), title=spec.get("title", spec["column"]),
                x_label=axis_label(spec["column"], spec.get("transform"), spec.get("unit")),
                log_y=options[spec.get("name", spec["column"])]["log_y"], on_reset=self._reset,
                colors={ALL: COLOR}, labels={ALL: "All observations"}, width=480, height=320,
            )
            for spec in config.get("hist1d", ())
        ]
        self.hist2d = []
        for spec in config.get("hist2d", ()):
            panel = Histogram2DPanel(
                spec.get("name", f"{spec['y']}_vs_{spec['x']}"), title=spec.get("title"),
                x_label=axis_label(spec["x"], spec.get("x_transform"), "deg"),
                y_label=axis_label(spec["y"], spec.get("y_transform"), "deg"), on_reset=self._reset,
                width=480, height=420,
            )
            # the origin: the target (sky map) or the centre of the field of view
            panel.figure.scatter(x=[0], y=[0], marker="cross", size=16, line_color="#e53935", line_width=2)
            self.hist2d.append(panel)
        self.reset_all = Button(label="Reset the DL3 data", width=160, button_type="danger")
        self.reset_all.on_click(lambda: self._reset())
        self.layout = column(
            Div(text="<h3 style='margin: 8px 0 0 0'>Observations</h3>"),
            row(self.observations, self.reset_all),
            self.rates.layout,
            row([p.layout for p in self.hist1d]),
            row([p.layout for p in self.hist2d]),
        )

    def _reset(self, name=None):
        """Forget the DL3 data received (or reset one histogram ``name``)"""
        self.store.dl3.reset(name)
        self.session.request_refresh()

    @staticmethod
    def _observations(observations):
        """Columns of the observations table from the summaries of `DL3Data.observations`"""
        data = {key: [] for key in ("obs_id", "object", "target", "pointing", "n_events", "livetime", "rate",
                                    "start", "stop")}
        for summary in observations:
            livetime = summary["livetime"]
            data["obs_id"].append(str(summary["obs_id"]))
            data["object"].append(summary["object"] or "–")
            data["target"].append(_position(summary["target"]))
            data["pointing"].append(_position(summary["pointing"]))
            data["n_events"].append(summary["n_events"])
            data["livetime"].append(format_number(livetime))
            data["rate"].append(format_number(summary["n_events"] / livetime) if livetime > 0 else "–")
            data["start"].append(_time(summary["start"]))
            data["stop"].append(_time(summary["stop"]))
        return data

    def refresh(self):
        """Show the observations, the rate and the histograms of the DL3 data"""
        dl3 = self.store.dl3
        data = self._observations(dl3.observations())
        if data != self.observations_source.data:
            self.observations_source.data = data
        self.rates.update({ALL: dl3.rate_history()})
        accumulators = dl3.statistics()["accumulators"]
        for panel in self.hist1d:
            panel.update({ALL: accumulators[panel.name]})
        for panel in self.hist2d:
            panel.update(accumulators[panel.name])
