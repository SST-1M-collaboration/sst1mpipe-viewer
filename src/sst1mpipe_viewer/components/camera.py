"""Camera display with its controls, based on the bokeh CameraDisplay of ctapipe"""

import numpy as np
from bokeh.events import Tap
from bokeh.layouts import column, row
from bokeh.models import Checkbox, ColorBar, ColumnDataSource, HoverTool, NumericInput, Select
from ctapipe.visualization.bokeh import CameraDisplay

from .histogram import add_caption

__all__ = ["CameraPanel", "CMAPS"]

CMAPS = ("inferno", "viridis", "magma", "gray")

MASK_COLOR = "#00e676"
SELECTED_COLOR = "#00b0ff"

TOOLS = "pan,wheel_zoom,box_zoom,reset,save"


class CameraPanel:
    """
    Camera image (ctapipe `~ctapipe.visualization.bokeh.CameraDisplay`) with a color bar,
    the choice of the colormap, of the linear or logarithmic scale and of the color range
    (automatic or fixed), the highlight of a pixel mask (e.g. the cleaning mask), of the
    selected pixels and a Hillas ellipse.

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
                 show_controls=True, on_pixel_tap=None, show_colorbar=True, selected_color=SELECTED_COLOR):
        self.display = CameraDisplay(
            geometry=None, cmap=cmap, title=title, width=width, height=height, tools=TOOLS,
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
        self._overlays = [ellipse, cog]

        # the clicked pixel is found from the position of the click: the bokeh selection would
        # fade the other pixels
        if on_pixel_click is not None or on_pixel_tap is not None:
            self.figure.on_event(Tap, self._tapped)

        self.cmap_select = Select(title="Colormap", value=cmap, options=list(CMAPS), width=95)
        self.scale_select = Select(title="Scale", value="lin", options=["lin", "log"], width=65)
        self.autoscale = Checkbox(label="Autoscale", active=True, width=85)
        self.low_input = NumericInput(title="Min", value=0, mode="float", width=75, disabled=True)
        self.high_input = NumericInput(title="Max", value=1, mode="float", width=75, disabled=True)
        self.cmap_select.on_change("value", lambda attr, old, new: self._set_cmap(new))
        self.scale_select.on_change("value", lambda attr, old, new: self._set_norm(new))
        self.autoscale.on_change("active", lambda attr, old, new: self._set_autoscale(new))
        self.low_input.on_change("value", lambda attr, old, new: self._apply_limits())
        self.high_input.on_change("value", lambda attr, old, new: self._apply_limits())

        self.caption = add_caption(self.figure)
        controls = row(self.cmap_select, self.scale_select, self.autoscale, self.low_input, self.high_input)
        self.layout = column(controls, self.figure) if show_controls else column(self.figure)

        if geometry is not None:
            self.set_geometry(geometry)

    # ----------------------------------------------------------------- setup
    def set_geometry(self, geometry):
        """Set the camera geometry (nothing is done if it is the current one)"""
        if geometry is self._geometry:
            return
        self._geometry = geometry
        self.display.geometry = geometry
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
        if self.autoscale.active:
            self._rescale()

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
        self._update_outline()

    def set_selected(self, pixels):
        """Outline the selected pixels (without calling ``on_pixel_click``)"""
        pixels = [int(p) for p in pixels if 0 <= int(p) < self.n_pixels]
        if pixels == self._selected:
            return
        self._selected = pixels
        self._update_outline()

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

    def _update_outline(self):
        n = self.n_pixels
        if n == 0:
            return
        width = np.zeros(n)
        alpha = np.zeros(n)
        color = np.full(n, MASK_COLOR, dtype=object)
        if self._mask is not None and self._mask.shape == (n,):
            width[self._mask] = 1.5
            alpha[self._mask] = 0.9
        if self._selected:
            width[self._selected] = 3
            alpha[self._selected] = 1.0
            color[self._selected] = self._selected_color
        self.display.datasource.patch({
            "line_width": [(slice(None), width)],
            "line_alpha": [(slice(None), alpha)],
            "line_color": [(slice(None), list(color))],
        })

    def _finite_values(self):
        values = np.asarray(self.display.datasource.data["values"], dtype=float)
        values = values[np.isfinite(values)]
        if self.scale_select.value == "log":
            values = values[values > 0]
        return values

    def _rescale(self):
        values = self._finite_values()
        if len(values) == 0:
            low, high = (1.0, 10.0) if self.scale_select.value == "log" else (0.0, 1.0)
        else:
            low, high = float(values.min()), float(values.max())
            if low == high:
                high = low * 10 if self.scale_select.value == "log" else low + 1
        # the inputs are not updated here: a change of a widget lays out the whole page again (slow),
        # they are filled with the current limits when the autoscale is switched off
        self.display.norm.update(low=low, high=high)

    def _apply_limits(self):
        if self.autoscale.active:
            return
        low, high = self.low_input.value, self.high_input.value
        if low is None or high is None or high <= low:
            return
        if self.scale_select.value == "log" and low <= 0:
            return
        self.display.norm.update(low=low, high=high)

    def _set_cmap(self, name):
        self.display.cmap = name

    def _set_norm(self, norm):
        self.display.norm = norm
        if self._color_bar is not None:
            self._color_bar.color_mapper = self.display.norm
        if self.autoscale.active:
            self._rescale()
        else:
            self._apply_limits()

    def _set_autoscale(self, active):
        self.low_input.disabled = active
        self.high_input.disabled = active
        if active:
            self._rescale()
        else:
            self.low_input.value, self.high_input.value = self.display.norm.low, self.display.norm.high
            self._apply_limits()
