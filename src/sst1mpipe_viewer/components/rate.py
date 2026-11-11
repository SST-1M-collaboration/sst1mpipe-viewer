"""Time series of the rates of the data received (`ViewerStore.rate_history`)"""

import numpy as np
from bokeh.models import ColumnDataSource, HoverTool, Legend, LegendItem
from bokeh.plotting import figure

__all__ = ["RatePanel"]


class RatePanel:
    """
    Rates in time with their uncertainties (error bars), one line per series (e.g. per telescope,
    or per data level), and vertical markers at chosen times (e.g. the time of the displayed event).

    Parameters
    ----------
    title : str
        Title of the plot.
    series : dict
        ``{key: (label, color)}`` of the lines.
    markers : dict or None
        ``{key: color}`` of the vertical markers (dashed lines), placed with `set_markers`.
    width, height : int
        Size of the plot (pixels).
    """

    def __init__(self, title, series, markers=None, width=1000, height=220):
        self.figure = figure(title=title, width=width, height=height, x_axis_type="datetime",
                             tools="xwheel_zoom,box_zoom,reset,save", toolbar_location="above")
        self.figure.yaxis.axis_label = "rate (Hz)"
        self.figure.title.text_font_size = "11pt"
        self.sources, self.renderers = {}, {}
        items = []
        for key, (label, color) in series.items():
            source = ColumnDataSource(data=dict(time=[], rate=[], error=[], lower=[], upper=[]))
            line = self.figure.line(x="time", y="rate", source=source, line_color=color, line_width=1.5)
            dots = self.figure.scatter(x="time", y="rate", source=source, color=color, size=5)
            # error bars: statistical uncertainty of the rate of each bin
            bars = self.figure.segment(x0="time", y0="lower", x1="time", y1="upper", source=source,
                                       line_color=color, line_width=1.5)
            self.sources[key], self.renderers[key] = source, (line, dots, bars)
            items.append(LegendItem(label=label, renderers=[line, dots, bars]))
        self.figure.add_layout(Legend(items=items, location="top_left", click_policy="hide",
                                      orientation="horizontal", background_fill_alpha=0.6))
        dots = [renderers[1] for renderers in self.renderers.values()]
        self.figure.add_tools(HoverTool(
            renderers=dots, formatters={"@time": "datetime"},
            tooltips=[("time", "@time{%F %T}"), ("rate", "@rate{0.00} ± @error{0.00} Hz")],
        ))
        # vertical lines (glyphs, not annotations: the time axis is extended to show them)
        self.markers = {}
        for key, color in (markers or {}).items():
            source = ColumnDataSource(data=dict(x=[]))
            self.figure.vspan(x="x", source=source, line_color=color, line_dash="dashed", line_width=2)
            self.markers[key] = source
        self.layout = self.figure

    def update(self, histories, visible=None):
        """
        Show rates.

        Parameters
        ----------
        histories : dict
            ``{key: (times, rates, errors)}``: centre of the bins (unix s), rates (Hz) and their
            uncertainties, for each series.
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
            times, rates, errors = (np.asarray(values, dtype=float) for values in histories[key])
            times_ms = times * 1000.0  # bokeh datetimes are in ms
            old = source.data
            if np.array_equal(times_ms, old["time"]) and np.array_equal(rates, old["rate"]):
                continue  # nothing new
            source.data = dict(time=times_ms, rate=rates, error=errors, lower=np.maximum(rates - errors, 0.0),
                               upper=rates + errors)

    def set_markers(self, times):
        """
        Place the vertical markers.

        Parameters
        ----------
        times : dict
            ``{key: time in unix s}``; the markers of the other keys, or with a None time, are hidden.
        """
        for key, source in self.markers.items():
            value = times.get(key)
            x = [] if value is None else [value * 1000.0]
            if list(source.data["x"]) != x:
                source.data = dict(x=x)
