"""Display of the waveforms of selected pixels"""

import numpy as np
from bokeh.models import ColumnDataSource, HoverTool, Legend, LegendItem, Span
from bokeh.palettes import Paired12
from bokeh.plotting import figure

__all__ = ["WaveformPanel", "waveform_2d"]

TOOLS = "pan,wheel_zoom,box_zoom,reset,save"
#: colors of the waveforms: 12, so that the 12 pixels of a module are all drawn
COLORS = Paired12
#: more pixels than this are shown by their mean waveform
MAX_PIXELS = len(COLORS)


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
    """
    Waveforms of up to `MAX_PIXELS` pixels (the mean waveform of more pixels), with a marker of a
    sample (e.g. the displayed one)
    """

    def __init__(self, title="Waveforms", y_label="", width=620, height=400, item_label="pixel"):
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
        # baselines (e.g. the DigiCam pedestal of the R0): dashed lines of the colors of the waveforms
        self.baseline_source = ColumnDataSource(data=dict(xs=[], ys=[], color=[]))
        self.figure.multi_line(xs="xs", ys="ys", line_color="color", line_width=1.5, line_dash="dashed",
                               source=self.baseline_source)
        self.item_label = item_label
        self._renderer = renderer
        self._legend_pixels = []
        self.layout = self.figure

    def set_waveforms(self, waveforms, pixels, sample=None, baselines=None):
        """
        Show the waveforms ``(n_pixels, n_samples)`` of the ``pixels`` (their mean if there are
        more than `MAX_PIXELS`), a marker at ``sample`` (None to hide it) and the ``baselines``
        of the pixels (one value per pixel, None for none) as dashed lines.
        """
        waveforms = np.asarray(waveforms, dtype=float)
        pixels = [int(p) for p in pixels if 0 <= int(p) < len(waveforms)]
        samples = np.arange(waveforms.shape[-1])
        if len(pixels) > MAX_PIXELS:
            # a group of pixels (e.g. a module or a sector): their mean waveform
            self._set_mean(waveforms, pixels, sample)
            self._set_baselines(samples, None if baselines is None else [np.nanmean(np.asarray(baselines)[pixels])],
                                ["black"])
            return

        colors = [COLORS[i % MAX_PIXELS] for i in range(len(pixels))]
        self._set_baselines(samples, None if baselines is None else np.asarray(baselines, dtype=float)[pixels], colors)
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
                LegendItem(label=f"{self.item_label} {p}", renderers=[self._renderer], index=i)
                for i, p in enumerate(pixels)
            ]
        self.sample_marker.visible = sample is not None
        if sample is not None:
            self.sample_marker.location = sample

    def _set_mean(self, waveforms, pixels, sample):
        """Show the mean waveform of the pixels (a group of pixels)"""
        samples = np.arange(waveforms.shape[-1])
        label = f"mean of {len(pixels)} {self.item_label}s"
        self.source.data = dict(xs=[samples], ys=[np.nanmean(waveforms[pixels], axis=0)], color=["black"],
                                pixel=[label])
        if self._legend_pixels != ("mean", len(pixels)):
            self._legend_pixels = ("mean", len(pixels))
            self.legend.items = [LegendItem(label=label, renderers=[self._renderer], index=0)]
        self.sample_marker.visible = sample is not None
        if sample is not None:
            self.sample_marker.location = sample

    def _set_baselines(self, samples, values, colors):
        """Dashed horizontal lines at the baseline of each shown pixel (``values`` None: none)"""
        if values is None:
            data = dict(xs=[], ys=[], color=[])
        else:
            ends = [samples[0], samples[-1]]
            data = dict(xs=[ends] * len(values), ys=[[v, v] for v in values], color=list(colors)[:len(values)])
        self.baseline_source.data = data

    def clear(self):
        """Show no waveform"""
        self.source.data = dict(xs=[], ys=[], color=[], pixel=[])
        self.baseline_source.data = dict(xs=[], ys=[], color=[])
        self.legend.items = []
        self._legend_pixels = []
        self.sample_marker.visible = False
