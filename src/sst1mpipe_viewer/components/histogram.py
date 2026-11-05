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
    Display of a `~sst1mpipe_viewer.accumulators.Histogram1D` snapshot, with its statistics
    (entries, mean, std, under/overflow) and a reset button calling ``on_reset``.
    """

    def __init__(self, name, title=None, x_label=None, log_y=False, on_reset=None, width=330, height=250):
        self.name = name
        self._ranges_set = False
        self._state = None
        self.log_y = log_y
        self.figure = figure(
            title=title or name, width=width, height=height, tools=TOOLS, toolbar_location="above",
            y_axis_type="log" if log_y else "linear", x_range=Range1d(0, 1),
        )
        self.figure.xaxis.axis_label = x_label or name
        self.figure.yaxis.axis_label = "entries"
        self.figure.title.text_font_size = "11pt"
        self.source = ColumnDataSource(data=dict(left=[], right=[], top=[], bottom=[]))
        self.figure.quad(left="left", right="right", top="top", bottom="bottom", source=self.source,
                         fill_color=FILL_COLOR, line_color=FILL_COLOR, fill_alpha=0.6)
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
        state = (snapshot["n_entries"], snapshot["n_invalid"], int(np.sum(snapshot["counts"])))
        if state == self._state:
            return
        self._state = state
        edges = snapshot["edges"]
        counts = np.asarray(snapshot["counts"], dtype=float)
        if not self._ranges_set:
            _set_range(self.figure.x_range, edges)
            self._ranges_set = True
        if self.log_y:
            # empty bins are not drawn on a log scale
            bottom = np.full_like(counts, 0.5)
            top = np.where(counts > 0, counts, np.nan)
        else:
            bottom = np.zeros_like(counts)
            top = counts
        self.source.data = dict(left=edges[:-1], right=edges[1:], top=top, bottom=bottom)
        self.stats.text = (
            f"N={snapshot['n_entries']}  mean={format_number(snapshot['mean'])}"
            f"  std={format_number(snapshot['std'])}"
            f"  under/over={snapshot['underflow']}/{snapshot['overflow']}"
            + (f"  invalid={snapshot['n_invalid']}" if snapshot["n_invalid"] else "")
        )


class Histogram2DPanel:
    """Display of a `~sst1mpipe_viewer.accumulators.Histogram2D` snapshot"""

    def __init__(self, name, title=None, x_label=None, y_label=None, on_reset=None, log_z=False,
                 width=380, height=330):
        self.name = name
        self._ranges_set = False
        self._state = None
        self.figure = figure(title=title or name, width=width, height=height, tools=TOOLS,
                             toolbar_location="above", x_range=Range1d(0, 1), y_range=Range1d(0, 1))
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
