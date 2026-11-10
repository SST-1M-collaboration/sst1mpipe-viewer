"""Displays of the accumulated histograms (`sst1mpipe_viewer.accumulators`)"""

import numpy as np
from bokeh.layouts import Spacer, column, row
from bokeh.models import Button, ColorBar, ColumnDataSource, LinearColorMapper, LogColorMapper, Range1d, Title
from bokeh.palettes import Viridis256
from bokeh.plotting import figure

__all__ = ["Histogram1DPanel", "Histogram2DPanel", "format_number", "add_caption"]

TOOLS = "pan,wheel_zoom,box_zoom,reset,save"
FILL_COLOR = "#3f6fb5"


def format_number(value):
    """Short representation of a number"""
    if value is None or not np.isfinite(value):
        return "–"
    if value != 0 and (abs(value) >= 1e4 or abs(value) < 1e-2):
        return f"{value:.3g}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def add_caption(fig, text=""):
    """
    Caption under a figure (a `~bokeh.models.Title`): unlike a ``Div``, changing its text does
    not lay out the whole page again, which is slow with many figures.
    """
    caption = Title(text=text, align="left", text_font_size="8.5pt", text_font_style="normal",
                    text_color="#555")
    fig.add_layout(caption, "below")
    return caption


def _set_range(axis_range, edges):
    """Range of an axis on the bins (the bins of a histogram do not change)"""
    start, end = float(edges[0]), float(edges[-1])
    axis_range.update(start=start, end=end, reset_start=start, reset_end=end)


class Histogram1DPanel:
    """
    Display of `~sst1mpipe_viewer.accumulators.Histogram1D` snapshots of several telescopes,
    superimposed with the color of each telescope, with their statistics (entries, mean, std,
    under/overflow) and a reset button calling ``on_reset``.

    Parameters
    ----------
    colors : dict
        Color of each telescope ``{tel_id: color}``.
    log_x, log_y : bool
        Logarithmic axes (``log_x`` for a histogram with logarithmic bins).
    labels : dict or None
        Name of each series in the captions ``{tel_id: label}``, ``TEL <tel_id>`` by default.
    """

    def __init__(self, name, title=None, x_label=None, log_y=False, on_reset=None, width=330, height=270,
                 colors=None, labels=None, log_x=False):
        self.name = name
        self._labels = labels or {}
        self._ranges_set = False
        self._states = {}
        self.log_y = log_y
        self.figure = figure(
            title=title or name, width=width, height=height, tools=TOOLS, toolbar_location="above",
            y_axis_type="log" if log_y else "linear", x_axis_type="log" if log_x else "linear",
            x_range=Range1d(1, 10) if log_x else Range1d(0, 1),
        )
        self.figure.xaxis.axis_label = x_label or name
        self.figure.yaxis.axis_label = "entries"
        self.figure.title.text_font_size = "11pt"
        colors = colors or {0: FILL_COLOR}
        self.sources, self.renderers = {}, {}
        for tel_id, color in colors.items():
            source = ColumnDataSource(data=dict(left=[], right=[], top=[], bottom=[]))
            self.sources[tel_id] = source
            self.renderers[tel_id] = self.figure.quad(
                left="left", right="right", top="top", bottom="bottom", source=source, fill_color=color,
                line_color=color, fill_alpha=0.3, line_width=1.5,
            )
        # statistics: one caption per telescope, with its color
        self.captions = {}
        for tel_id, color in colors.items():
            self.captions[tel_id] = add_caption(self.figure)
            self.captions[tel_id].text_color = color
        self.reset_button = Button(label="Reset", width=60, height=26, button_type="light")
        if on_reset is not None:
            self.reset_button.on_click(lambda: on_reset(self.name))
        self.layout = column(self.figure, row(Spacer(width=width - 70), self.reset_button))

    def invalidate(self):
        """Show the next snapshots even if they look like the last ones"""
        self._states = {}

    def update(self, snapshots):
        """
        Show the snapshots of the telescopes ``{tel_id: snapshot}`` (the other telescopes are
        hidden; nothing is sent for a snapshot which did not change since the last update)
        """
        for tel_id, source in self.sources.items():
            renderer = self.renderers[tel_id]
            snapshot = snapshots.get(tel_id)
            if renderer.visible != (snapshot is not None):
                renderer.visible = snapshot is not None
            label = self._labels.get(tel_id, f"TEL {tel_id}")
            text = "" if snapshot is None else (
                f"{label}: N={snapshot['n_entries']} mean={format_number(snapshot['mean'])}"
                f" std={format_number(snapshot['std'])} out={snapshot['underflow']}/{snapshot['overflow']}"
            )
            if self.captions[tel_id].text != text:
                self.captions[tel_id].text = text
            if snapshot is None:
                continue
            state = (snapshot["n_entries"], snapshot["n_invalid"], int(np.sum(snapshot["counts"])))
            if state == self._states.get(tel_id):
                continue
            self._states[tel_id] = state
            edges = snapshot["edges"]
            counts = np.asarray(snapshot["counts"], dtype=float)
            if not self._ranges_set:
                _set_range(self.figure.x_range, edges)
                self._ranges_set = True
            # the empty bins are not drawn (no flat line over the histograms of the other telescopes)
            bottom = np.full_like(counts, 0.5 if self.log_y else 0.0)
            top = np.where(counts > 0, counts, np.nan)
            source.data = dict(left=edges[:-1], right=edges[1:], top=top, bottom=bottom)


class Histogram2DPanel:
    """Display of a `~sst1mpipe_viewer.accumulators.Histogram2D` snapshot"""

    def __init__(self, name, title=None, x_label=None, y_label=None, on_reset=None, log_z=False,
                 width=380, height=330, log_x=False, log_y=False):
        self.name = name
        self._ranges_set = False
        self._state = None
        # logarithmic bins are drawn on a logarithmic axis, where they have the same width
        self.figure = figure(title=title or name, width=width, height=height, tools=TOOLS, toolbar_location="above",
                             x_axis_type="log" if log_x else "linear", y_axis_type="log" if log_y else "linear",
                             x_range=Range1d(1, 10) if log_x else Range1d(0, 1),
                             y_range=Range1d(1, 10) if log_y else Range1d(0, 1))
        self.figure.xaxis.axis_label = x_label or ""
        self.figure.yaxis.axis_label = y_label or ""
        self.figure.title.text_font_size = "11pt"
        self.figure.grid.visible = False
        mapper_class = LogColorMapper if log_z else LinearColorMapper
        self.color_mapper = mapper_class(palette=Viridis256, low=0, high=1, low_color="white")
        self.source = ColumnDataSource(data=dict(image=[], x=[], y=[], dw=[], dh=[]))
        self.figure.image(image="image", x="x", y="y", dw="dw", dh="dh", source=self.source,
                          color_mapper=self.color_mapper)
        self.figure.add_layout(ColorBar(color_mapper=self.color_mapper, width=10, border_line_color=None), "right")
        self.stats = add_caption(self.figure)
        self.reset_button = Button(label="Reset", width=60, height=26, button_type="light")
        if on_reset is not None:
            self.reset_button.on_click(lambda: on_reset(self.name))
        self.layout = column(self.figure, row(Spacer(width=width - 70), self.reset_button))

    def invalidate(self):
        """Show the next snapshot even if it looks like the last one"""
        self._state = None

    def update(self, snapshot):
        """Show a snapshot (nothing is done if it did not change since the last update)"""
        state = (snapshot["n_entries"], int(np.sum(snapshot["counts"])))
        if state == self._state:
            return
        self._state = state
        x_edges, y_edges = snapshot["x_edges"], snapshot["y_edges"]
        counts = np.asarray(snapshot["counts"], dtype=float)
        if not self._ranges_set:
            _set_range(self.figure.x_range, x_edges)
            _set_range(self.figure.y_range, y_edges)
            self._ranges_set = True
        # empty bins below the low limit are shown in white
        self.color_mapper.update(low=0.5, high=max(float(counts.max()), 1.0))
        self.source.data = dict(
            image=[counts.T], x=[x_edges[0]], y=[y_edges[0]],
            dw=[x_edges[-1] - x_edges[0]], dh=[y_edges[-1] - y_edges[0]],
        )
        self.stats.text = f"N={snapshot['n_entries']}  in range={int(counts.sum())}"
