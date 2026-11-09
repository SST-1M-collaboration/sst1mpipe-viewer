"""Time series of the rates of the data received (`ViewerStore.rate_history`)"""

import numpy as np
from bokeh.models import ColumnDataSource, HoverTool, Legend, LegendItem
from bokeh.plotting import figure

__all__ = ["RatePanel"]


class RatePanel:
    """
    Rates in time, one line per series (e.g. per telescope, or per data level).

    Parameters
    ----------
    title : str
        Title of the plot.
    series : dict
        ``{key: (label, color)}`` of the lines.
    width, height : int
        Size of the plot (pixels).

    Use `update` with the rates of the series. A line whose rates only grew by new bins at the
    end is updated by sending these bins only (``ColumnDataSource.stream``), not all its points.
    """

    def __init__(self, title, series, width=1000, height=220):
        self.figure = figure(title=title, width=width, height=height, x_axis_type="datetime",
                             tools="pan,xwheel_zoom,box_zoom,reset,save", toolbar_location="above")
        self.figure.yaxis.axis_label = "rate (Hz)"
        self.figure.title.text_font_size = "11pt"
        self.sources, self.renderers = {}, {}
        items = []
        for key, (label, color) in series.items():
            source = ColumnDataSource(data=dict(time=[], rate=[]))
            line = self.figure.line(x="time", y="rate", source=source, line_color=color, line_width=2)
            # markers: a series of a single bin is visible
            dots = self.figure.scatter(x="time", y="rate", source=source, color=color, size=4)
            self.sources[key], self.renderers[key] = source, (line, dots)
            items.append(LegendItem(label=label, renderers=[line, dots]))
        self.figure.add_layout(Legend(items=items, location="top_left", click_policy="hide",
                                      orientation="horizontal", background_fill_alpha=0.6))
        lines = [line for line, _ in self.renderers.values()]
        self.figure.add_tools(HoverTool(renderers=lines, tooltips=[("time", "@time{%F %T}"), ("rate", "@rate{0.0} Hz")],
                                        formatters={"@time": "datetime"}, mode="vline"))
        self.layout = self.figure

    def update(self, histories, visible=None):
        """
        Show rates.

        Parameters
        ----------
        histories : dict
            ``{key: (times, rates)}``: start of the bins (unix s) and rates (Hz) of the series.
        visible : iterable or None
            Keys of the series shown (all if None).
        """
        for key, source in self.sources.items():
            shown = visible is None or key in visible
            for renderer in self.renderers[key]:
                if renderer.visible != shown:
                    renderer.visible = shown
            if not shown or key not in histories:
                continue
            times, rates = histories[key]
            times_ms = np.asarray(times, dtype=float) * 1000.0  # bokeh datetimes are in ms
            old = source.data["time"]
            if (len(old) and len(times_ms) == len(old) and times_ms[-1] == old[-1]
                    and np.array_equal(rates, source.data["rate"])):
                continue  # nothing new
            if len(old) and len(times_ms) and times_ms[0] <= old[-1] < times_ms[-1]:
                # new bins at the end: only these are sent
                new = times_ms > old[-1]
                source.stream(dict(time=times_ms[new], rate=np.asarray(rates)[new]), rollover=len(times_ms))
            else:
                source.data = dict(time=times_ms, rate=np.asarray(rates, dtype=float))
