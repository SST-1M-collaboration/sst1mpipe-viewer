"""Display of the telescope array, based on the bokeh ArrayDisplay of ctapipe"""

import numpy as np
from bokeh.models import ColumnDataSource, LabelSet, TapTool
from ctapipe.visualization.bokeh import ArrayDisplay

__all__ = ["ArrayPanel"]

SELECTED_COLOR = "#00b0ff"
ACTIVE_COLOR = "#00c853"


class ArrayPanel:
    """
    Ground view of the telescopes of a subarray (ctapipe
    `~ctapipe.visualization.bokeh.ArrayDisplay`, colored by telescope type), with the
    telescope ids, a ring around the selected telescope and a dot on the telescopes
    receiving data. ``on_tel_click(tel_id)`` is called when a telescope is clicked.
    """

    def __init__(self, subarray, on_tel_click=None, width=640, height=560, scale=8.0):
        self.subarray = subarray
        self.display = ArrayDisplay(
            subarray, scale=scale, width=width, height=height, use_notebook=False,
            tools="pan,wheel_zoom,box_zoom,reset,save", toolbar_location="above",
            title=f"{subarray.name or 'Array'}: telescope positions (ground frame)",
        )
        self.figure = self.display.figure
        self.figure.xaxis.axis_label = "x (m)"
        self.figure.yaxis.axis_label = "y (m)"
        data = self.display.datasource.data
        self.tel_ids = [int(i) for i in data["id"]]
        x, y, radius = (np.asarray(data[k], dtype=float) for k in ("x", "y", "radius"))
        self._x, self._y, self._radius = x, y, radius

        # the telescopes and their labels are not on the border
        self.figure.x_range.range_padding = 0.3
        self.figure.y_range.range_padding = 0.3

        labels = ColumnDataSource(data=dict(
            x=x, y=y + radius * 1.6, text=[f"TEL {i}" for i in self.tel_ids],
        ))
        self.figure.add_layout(LabelSet(x="x", y="y", text="text", source=labels, text_align="center",
                                        text_font_size="11pt", text_font_style="bold"))

        self._ring = ColumnDataSource(data=dict(x=[], y=[], radius=[]))
        self.figure.circle(x="x", y="y", radius="radius", source=self._ring, fill_color=None,
                           line_color=SELECTED_COLOR, line_width=3)
        self._active = ColumnDataSource(data=dict(x=[], y=[]))
        self.figure.scatter(x="x", y="y", source=self._active, size=10, marker="circle",
                            fill_color=ACTIVE_COLOR, line_color="white")

        self._on_tel_click = on_tel_click
        renderer = self.display._patches
        if on_tel_click is not None:
            self.figure.add_tools(TapTool(renderers=[renderer]))
            self.display.datasource.selected.on_change("indices", self._clicked)
        self.layout = self.figure

    def _clicked(self, attr, old, new):
        if new:
            self._on_tel_click(self.tel_ids[new[0]])
            # the selection is shown by the ring
            self.display.datasource.selected.indices = []

    def set_selected(self, tel_id):
        if tel_id in self.tel_ids:
            i = self.tel_ids.index(tel_id)
            self._ring.data = dict(x=[self._x[i]], y=[self._y[i]], radius=[self._radius[i] * 1.4])
        else:
            self._ring.data = dict(x=[], y=[], radius=[])

    def set_active(self, tel_ids):
        """Mark the telescopes receiving data"""
        indices = [self.tel_ids.index(t) for t in tel_ids if t in self.tel_ids]
        self._active.data = dict(x=self._x[indices], y=self._y[indices])
