"""
DL3 page: the gamma-ray candidates of the observations (`sst1mpipe_viewer.dl3`).

The page shows the observations received, the rate of their events in time and the accumulated
histograms (energy, theta^2 to the target, sky map around the target, position in the field of
view). In a mono analysis (one DL3 file per telescope) there is one series per telescope, with
its color: the 1D histograms are superimposed and the maps are side by side. In a stereo analysis
there is a single series, that of the subarray.
"""

from astropy.time import Time
from bokeh.layouts import column, row
from bokeh.models import Button, ColumnDataSource, DataTable, Div, TableColumn

from ..components import Histogram1DPanel, Histogram2DPanel, RatePanel
from ..components.histogram import format_number
from ..config import display_options
from ..dl2 import SUBARRAY_ID
from .base import Page
from .statistics import axis_label

__all__ = ["DL3Page"]

#: color of the stereo DL3 plots
STEREO_COLOR = "#7b3294"


def _position(position):
    """Text of a sky position (ra, dec) in deg"""
    return "–" if position is None else f"{position[0]:.3f}, {position[1]:.3f}"


def _time(unix):
    """ISO date of a unix time, '–' if unknown"""
    return Time(unix, format="unix").isot[:19] if unix == unix else "–"


class DL3Page(Page):
    """The DL3 events of the observations: observations table, rate in time, histograms per series"""

    title = "DL3"

    def __init__(self, session):
        super().__init__(session)
        config = self.store.dl3.config
        options = display_options(config)
        # the possible series: each telescope (mono analysis) and the subarray (stereo analysis)
        all_series = [*session.all_tel_ids, SUBARRAY_ID]
        colors = {s: STEREO_COLOR if s == SUBARRAY_ID else session.color(s) for s in all_series}
        labels = {s: session.tel_label(s) for s in all_series}
        self._labels = labels
        self.observations_source = ColumnDataSource(data=self._observations([]))
        self.observations = DataTable(source=self.observations_source, index_position=None, width=1200, height=110,
                                      columns=[
            TableColumn(field="series", title="Analysis", width=90),
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
        self.rates = RatePanel("Rate of the DL3 events per minute", {s: (labels[s], colors[s]) for s in all_series},
                               width=1100, height=220)
        self.hist1d = [
            Histogram1DPanel(
                spec.get("name", spec["column"]), title=spec.get("title", spec["column"]),
                x_label=axis_label(spec["column"], spec.get("transform"), spec.get("unit")),
                on_reset=self._reset, colors=colors, labels=labels, width=480, height=320,
                **options[spec.get("name", spec["column"])],
            )
            for spec in config.get("hist1d", ())
        ]
        # the maps: one per series
        self.hist2d = {}
        for spec in config.get("hist2d", ()):
            name = spec.get("name", f"{spec['y']}_vs_{spec['x']}")
            for series in all_series:
                panel = Histogram2DPanel(
                    name, title=f"{spec.get('title') or name} – {labels[series]}",
                    x_label=axis_label(spec["x"], spec.get("x_transform"), "deg"),
                    y_label=axis_label(spec["y"], spec.get("y_transform"), "deg"), on_reset=self._reset,
                    width=480, height=420, **options[name],
                )
                panel.figure.title.text_color = colors[series]
                # the origin: the target (sky map) or the centre of the field of view
                panel.figure.scatter(x=[0], y=[0], marker="cross", size=16, line_color="#e53935", line_width=2)
                self.hist2d[(name, series)] = panel
        self._hist2d_names = list(dict.fromkeys(name for name, _ in self.hist2d))
        self.maps = column()
        self._shown_series = None
        self.reset_all = Button(label="Reset the DL3 data", width=160, button_type="danger")
        self.reset_all.on_click(lambda: self._reset())
        self.layout = column(
            Div(text="<h3 style='margin: 8px 0 0 0'>Observations</h3>"),
            row(self.observations, self.reset_all),
            self.rates.layout,
            row([p.layout for p in self.hist1d]),
            self.maps,
        )

    def _reset(self, name=None):
        """Forget the DL3 data received (or reset one histogram ``name``)"""
        self.store.dl3.reset(name)
        self.session.request_refresh()

    def _observations(self, observations):
        """Columns of the observations table from the summaries of `DL3Data.observations`"""
        data = {key: [] for key in ("series", "obs_id", "object", "target", "pointing", "n_events", "livetime",
                                    "rate", "start", "stop")}
        for summary in observations:
            livetime = summary["livetime"]
            data["series"].append(self._labels.get(summary["series"], str(summary["series"])))
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

    def _set_layout(self, series):
        """Maps of the series with events (the layout changes only when the series change)"""
        if series == self._shown_series:
            return
        self._shown_series = series
        self.maps.children = [row([self.hist2d[(name, s)].layout for s in series]) for name in self._hist2d_names]
        for panel in self.hist1d:
            panel.invalidate()

    def refresh(self):
        """Show the observations, the rates and the histograms of the series with DL3 events"""
        dl3 = self.store.dl3
        series = [s for s in dl3.series() if s in self._labels]  # the telescopes known when the page was built
        self._set_layout(series)
        data = self._observations(dl3.observations())
        if data != self.observations_source.data:
            self.observations_source.data = data
        self.rates.update({s: dl3.rate_history(s) for s in series}, visible=series)
        accumulators = {s: dl3.statistics(s)["accumulators"] for s in series}
        for panel in self.hist1d:
            panel.update({s: accumulators[s][panel.name] for s in series})
        for (name, s), panel in self.hist2d.items():
            if s in accumulators:
                panel.update(accumulators[s][name])
