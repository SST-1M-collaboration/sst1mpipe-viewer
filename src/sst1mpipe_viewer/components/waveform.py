"""Display of the waveforms of selected pixels"""

import numpy as np
from bokeh.models import ColumnDataSource, HoverTool, Legend, LegendItem, Span
from bokeh.palettes import Category10_10
from bokeh.plotting import figure

__all__ = ["WaveformPanel", "waveform_2d"]

TOOLS = "pan,wheel_zoom,box_zoom,reset,save"
MAX_PIXELS = len(Category10_10)


def waveform_2d(waveform, channel=0):
    """
    Waveforms ``(n_pixels, n_samples)`` of an R0/R1/DL0 waveform of shape
    ``(n_channels, n_pixels, n_samples)`` (gain ``channel``) or ``(n_pixels, n_samples)``.
    """
    waveform = np.asarray(waveform)
    if waveform.ndim == 3:
        return waveform[min(channel, waveform.shape[0] - 1)]
    if waveform.ndim == 2:
        return waveform
    raise ValueError(f"Unexpected waveform shape {waveform.shape}")


class WaveformPanel:
    """Waveforms of up to `MAX_PIXELS` pixels, with a marker of a sample (e.g. the displayed one)"""

    def __init__(self, title="Waveforms", y_label="", width=620, height=400):
        self.figure = figure(title=title, width=width, height=height, tools=TOOLS, toolbar_location="above")
        self.figure.xaxis.axis_label = "sample"
        self.figure.yaxis.axis_label = y_label
        self.source = ColumnDataSource(data=dict(xs=[], ys=[], color=[], pixel=[]))
        renderer = self.figure.multi_line(xs="xs", ys="ys", line_color="color", line_width=2, source=self.source)
        self.figure.add_tools(HoverTool(renderers=[renderer], tooltips=[("pixel", "@pixel")]))
        self.legend = Legend(items=[], location="top_right")
        self.figure.add_layout(self.legend)
        self.sample_marker = Span(location=0, dimension="height", line_color="#999", line_dash="dashed",
                                  visible=False)
        self.figure.add_layout(self.sample_marker)
        self._renderer = renderer
        self._legend_pixels = []
        self.layout = self.figure

    def set_y_label(self, label):
        self.figure.yaxis.axis_label = label

    def set_waveforms(self, waveforms, pixels, sample=None):
        """
        Show the waveforms ``(n_pixels, n_samples)`` of the ``pixels`` (the first `MAX_PIXELS`)
        and a marker at ``sample`` (None to hide it).
        """
        waveforms = np.asarray(waveforms, dtype=float)
        pixels = [int(p) for p in pixels if 0 <= int(p) < len(waveforms)][:MAX_PIXELS]
        samples = np.arange(waveforms.shape[-1])
        colors = [Category10_10[i % MAX_PIXELS] for i in range(len(pixels))]
        self.source.data = dict(
            xs=[samples] * len(pixels),
            ys=[waveforms[p] for p in pixels],
            color=colors,
            pixel=[str(p) for p in pixels],
        )
        if pixels != self._legend_pixels:
            # new legend items only when the pixels change (new models are costly to send)
            self._legend_pixels = pixels
            self.legend.items = [
                LegendItem(label=f"pixel {p}", renderers=[self._renderer], index=i) for i, p in enumerate(pixels)
            ]
        self.sample_marker.visible = sample is not None
        if sample is not None:
            self.sample_marker.location = sample

    def clear(self):
        self.source.data = dict(xs=[], ys=[], color=[], pixel=[])
        self.legend.items = []
        self._legend_pixels = []
        self.sample_marker.visible = False
