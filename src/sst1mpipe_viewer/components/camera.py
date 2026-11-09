"""Camera display based on the bokeh CameraDisplay of ctapipe"""

import numpy as np
from bokeh.events import Tap
from bokeh.layouts import column
from bokeh.models import ColorBar, ColumnDataSource, HoverTool
from ctapipe.visualization.bokeh import CameraDisplay

from .histogram import add_caption

__all__ = ["CameraPanel", "COLOR_SCALES"]

#: color scales of the cameras (configured when the viewer is started, not in the pages)
COLOR_SCALES = ("lin", "log")

MASK_COLOR = "#00e676"
SELECTED_COLOR = "#00b0ff"

TOOLS = "pan,wheel_zoom,box_zoom,reset,save"


class CameraPanel:
    """
    Camera image (ctapipe `~ctapipe.visualization.bokeh.CameraDisplay`) with a color bar (color
    range adjusted to the values), the outline of a pixel mask (e.g. the cleaning mask) and of the
    selected pixels, and a Hillas ellipse. The colormap and the linear or logarithmic color scale
    are set when the viewer is started (no widget in the pages, lighter to navigate).

    Parameters
    ----------
    geometry : ctapipe.instrument.CameraGeometry or None
        Geometry of the camera, it can be set later with `set_geometry`.
    title : str
        Title of the figure.
    on_pixel_click : callable or None
        Called with the list of the selected pixels when pixels are clicked
        (shift+click to select several pixels).
    on_pixel_tap : callable or None
        Called with the clicked pixel and whether shift was pressed, instead of the selection
        of the clicked pixels (e.g. to select a group of pixels).
    """

    def __init__(self, geometry=None, title="", cmap="inferno", width=440, height=400, on_pixel_click=None,
                 on_pixel_tap=None, show_colorbar=True, selected_color=SELECTED_COLOR, scale="lin"):
        if scale not in COLOR_SCALES:
            raise ValueError(f"Unknown color scale {scale!r}, known: {COLOR_SCALES}")
        self.scale = scale
        self.display = CameraDisplay(
            geometry=None, cmap=cmap, norm=scale, title=title, width=width, height=height, tools=TOOLS,
            use_notebook=False, toolbar_location="above",
        )
        self.figure = self.display.figure
        self.figure.title.text = title
        self.figure.axis.visible = True
        self.figure.grid.visible = False
        self._on_pixel_click = on_pixel_click
        self._on_pixel_tap = on_pixel_tap
        self._show_colorbar = show_colorbar
        self._selected_color = selected_color
        self._hover_label = None
        self._mask = None
        self._selected = []
        self._geometry = None
        self._color_bar = None

        self._ellipse_source = ColumnDataSource(data=dict(x=[], y=[], width=[], height=[], angle=[]))
        ellipse = self.figure.ellipse(
            x="x", y="y", width="width", height="height", angle="angle", source=self._ellipse_source,
            fill_color=None, line_color=SELECTED_COLOR, line_width=2,
        )
        cog = self.figure.scatter(x="x", y="y", source=self._ellipse_source, marker="cross", size=12,
                                  line_color=SELECTED_COLOR, line_width=2)
        # outlines of the pixels of the mask (e.g. the cleaning) and of the selected pixels: layers
        # with only these pixels (cheaper than changing the line of all the pixels)
        self._xs, self._ys = [], []
        self._mask_source = ColumnDataSource(data=dict(xs=[], ys=[]))
        mask = self.figure.patches(xs="xs", ys="ys", source=self._mask_source, fill_color=None,
                                   line_color=MASK_COLOR, line_width=1.5, line_alpha=0.9)
        self._selected_source = ColumnDataSource(data=dict(xs=[], ys=[]))
        selected = self.figure.patches(xs="xs", ys="ys", source=self._selected_source, fill_color=None,
                                       line_color=selected_color, line_width=3)
        self._overlays = [mask, selected, ellipse, cog]

        # the clicked pixel is found from the position of the click: the bokeh selection would
        # fade the other pixels
        if on_pixel_click is not None or on_pixel_tap is not None:
            self.figure.on_event(Tap, self._tapped)

        self.caption = add_caption(self.figure)
        self.layout = column(self.figure)

        if geometry is not None:
            self.set_geometry(geometry)

    # ----------------------------------------------------------------- setup
    def _same_camera(self, geometry):
        current = self._geometry
        return (
            current is not None and geometry.n_pixels == current.n_pixels and geometry.pix_type == current.pix_type
            and geometry.pix_x.unit == current.pix_x.unit
            and np.allclose(geometry.pix_x.value, current.pix_x.value)
            and np.allclose(geometry.pix_y.value, current.pix_y.value)
        )

    def set_geometry(self, geometry):
        """
        Set the camera geometry. Nothing is sent to the browser if it is the current one, or a
        camera of the same type (same pixels, e.g. another SST-1M telescope)
        """
        if geometry is self._geometry:
            return
        if self._same_camera(geometry):
            self._geometry = geometry
            return
        self._geometry = geometry
        self.display.geometry = geometry
        data = self.display.datasource.data
        if geometry.pix_type.name in ("HEXAGON", "SQUARE"):
            self._xs, self._ys = data["xs"], data["ys"]
        else:  # circles: no outline layers
            self._xs, self._ys = [], []
        # the tooltip is that of the pixels (not of the overlays)
        for tool in self.figure.select(HoverTool):
            tool.renderers = [self.display._patches]
        # the overlays are drawn over the pixels
        self.figure.renderers = [r for r in self.figure.renderers if r not in self._overlays] + self._overlays
        if self._color_bar is None:
            self._color_bar = ColorBar(color_mapper=self.display.norm, label_standoff=8, border_line_color=None,
                                       width=12, visible=self._show_colorbar)
            self.figure.add_layout(self._color_bar, "right")
        unit = geometry.pix_x.unit
        self.figure.xaxis.axis_label = f"x ({unit})" if geometry.frame is None else f"fov_lon ({unit})"
        self.figure.yaxis.axis_label = f"y ({unit})" if geometry.frame is None else f"fov_lat ({unit})"
        self._mask = None
        self._selected = []
        self._update_outline()

    @property
    def geometry(self):
        return self._geometry

    @property
    def n_pixels(self):
        return 0 if self._geometry is None else self._geometry.n_pixels

    # ---------------------------------------------------------------- update
    def set_title(self, title):
        self.figure.title.text = title

    def set_hover_column(self, label, values):
        """Show ``values`` (one per pixel, e.g. the group of each pixel) in the tooltip of the pixels"""
        if self._geometry is None:
            return
        source = self.display.datasource
        source.data = {**source.data, "extra": np.asarray(values)}
        if self._hover_label != label:
            self._hover_label = label
            for tool in self.figure.select(HoverTool):
                tool.tooltips = [("pixel", "@id"), (label, "@extra")]

    def set_caption(self, text):
        """Text under the camera (e.g. the event or the number of entries)"""
        self.caption.text = text

    def set_image(self, values):
        """Set the values of the pixels (NaN values are shown in grey)"""
        if self._geometry is None:
            return
        values = np.asarray(values, dtype=float)
        if values.shape != (self.n_pixels,):
            raise ValueError(f"Expected {self.n_pixels} values, got an array of shape {values.shape}")
        self.display.datasource.patch({"values": [(slice(None), values)]})
        self._rescale(values)

    def clear(self):
        """Show an empty camera"""
        if self._geometry is not None:
            self.set_image(np.full(self.n_pixels, np.nan))
        self.set_mask(None)
        self.set_ellipse(None)

    def set_mask(self, mask):
        """Outline the pixels of a boolean mask (None to remove)"""
        mask = None if mask is None else np.asarray(mask, dtype=bool)
        if (mask is None and self._mask is None) or (
            mask is not None and self._mask is not None and np.array_equal(mask, self._mask)
        ):
            return
        self._mask = mask
        self._update_mask()

    def set_selected(self, pixels):
        """Outline the selected pixels (without calling ``on_pixel_click``)"""
        pixels = [int(p) for p in pixels if 0 <= int(p) < self.n_pixels]
        if pixels == self._selected:
            return
        self._selected = pixels
        self._update_selected()

    def set_ellipse(self, hillas):
        """
        Draw the Hillas ellipse (1 sigma) of a dict with ``hillas_fov_lon``, ``hillas_fov_lat``,
        ``hillas_length``, ``hillas_width`` and ``hillas_psi`` (deg); None or non finite
        parameters remove it.
        """
        data = dict(x=[], y=[], width=[], height=[], angle=[])
        if hillas is not None:
            keys = ("hillas_fov_lon", "hillas_fov_lat", "hillas_length", "hillas_width", "hillas_psi")
            values = [float(hillas.get(k, np.nan)) for k in keys]
            if all(np.isfinite(values)):
                lon, lat, length, width, psi = values
                data = dict(x=[lon], y=[lat], width=[2 * length], height=[2 * width], angle=[np.deg2rad(psi)])
        self._ellipse_source.data = data

    # -------------------------------------------------------------- internal
    def pixel_at(self, x, y):
        """Pixel at the position (x, y) in the units of the geometry, None outside of the pixels"""
        if self._geometry is None or x is None or y is None:
            return None
        geometry = self._geometry
        unit = geometry.pix_x.unit
        distance = np.hypot(geometry.pix_x.to_value(unit) - x, geometry.pix_y.to_value(unit) - y)
        pixel = int(np.argmin(distance))
        # within the circumcircle of a hexagonal or square pixel
        if distance[pixel] > 0.6 * geometry.pixel_width.to_value(unit)[pixel]:
            return None
        return pixel

    def _tapped(self, event):
        pixel = self.pixel_at(event.x, event.y)
        if pixel is None:
            return
        shift = bool(event.modifiers and event.modifiers.get("shift"))
        if self._on_pixel_tap is not None:
            self._on_pixel_tap(pixel, shift)
            return
        if shift:
            # shift+click adds or removes a pixel
            pixels = [p for p in self._selected if p != pixel]
            if len(pixels) == len(self._selected):
                pixels.append(pixel)
        else:
            pixels = [pixel]
        self.set_selected(pixels)
        self._on_pixel_click(pixels)

    def _outlines(self, pixels):
        pixels = [p for p in pixels if p < len(self._xs)]
        return dict(xs=[self._xs[p] for p in pixels], ys=[self._ys[p] for p in pixels])

    def _update_mask(self):
        mask = self._mask
        pixels = [] if mask is None or mask.shape != (self.n_pixels,) else np.flatnonzero(mask).tolist()
        self._mask_source.data = self._outlines(pixels)

    def _update_selected(self):
        self._selected_source.data = self._outlines(self._selected)

    def _update_outline(self):
        self._update_mask()
        self._update_selected()

    def _rescale(self, values):
        """Color range on the finite values (positive ones for a log scale)"""
        log = self.scale == "log"
        values = values[np.isfinite(values)]
        if log:
            values = values[values > 0]
        if len(values) == 0:
            low, high = (1.0, 10.0) if log else (0.0, 1.0)
        else:
            low, high = float(values.min()), float(values.max())
            if low == high:
                high = low * 10 if log else low + 1
        if (self.display.norm.low, self.display.norm.high) != (low, high):
            self.display.norm.update(low=low, high=high)
