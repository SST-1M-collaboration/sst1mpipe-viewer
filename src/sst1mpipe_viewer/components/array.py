"""Display of the telescope array, based on the bokeh ArrayDisplay of ctapipe"""

import numpy as np
from bokeh.models import ColumnDataSource, HoverTool, LabelSet, TapTool
from bokeh.plotting import figure
from ctapipe.visualization.bokeh import ArrayDisplay

__all__ = ["ArrayMapPanel", "ArrayPanel", "earth_locations", "web_mercator"]

SELECTED_COLOR = "#00b0ff"
ACTIVE_COLOR = "#00c853"


class ArrayPanel:
    """
    Ground view of the telescopes of a subarray (ctapipe
    `~ctapipe.visualization.bokeh.ArrayDisplay`, colored by telescope type), with the
    telescope ids, a ring around the selected telescope and a dot on the telescopes
    receiving data. ``on_tel_click(tel_id)`` is called when a telescope is clicked.
    """

    def __init__(self, subarray, on_tel_click=None, width=640, height=560, scale=8.0, colors=None):
        self._colors = colors or {}
        self.subarray = subarray
        self.display = ArrayDisplay(
            subarray, scale=scale, width=width, height=height, use_notebook=False,
            tools="wheel_zoom,box_zoom,reset,save", toolbar_location="above",
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

        self._ring = ColumnDataSource(data=dict(x=[], y=[], radius=[], color=[]))
        self.figure.circle(x="x", y="y", radius="radius", source=self._ring, fill_color=None,
                           line_color="color", line_width=4)
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
        """A telescope was clicked: ``on_tel_click(tel_id)`` (the click selection is not kept)"""
        if new:
            self._on_tel_click(self.tel_ids[new[0]])
            # the selection is shown by the ring
            self.display.datasource.selected.indices = []

    def set_selected(self, tel_ids):
        """Ring of the color of each selected telescope"""
        indices = [self.tel_ids.index(t) for t in tel_ids if t in self.tel_ids]
        data = dict(x=self._x[indices], y=self._y[indices], radius=self._radius[indices] * 1.4,
                    color=[self._colors.get(self.tel_ids[i], SELECTED_COLOR) for i in indices])
        if any(not np.array_equal(data[k], self._ring.data.get(k, [])) for k in ("x", "y")):
            self._ring.data = data

    def set_active(self, tel_ids):
        """Mark the telescopes receiving data"""
        indices = [self.tel_ids.index(t) for t in tel_ids if t in self.tel_ids]
        self._active.data = dict(x=self._x[indices], y=self._y[indices])


#: radius of the Earth of the web Mercator projection (m)
_MERCATOR_RADIUS = 6378137.0


def web_mercator(lon_deg, lat_deg):
    """Web Mercator coordinates (m) of longitudes and latitudes (deg)"""
    lon, lat = np.deg2rad(np.asarray(lon_deg, dtype=float)), np.deg2rad(np.asarray(lat_deg, dtype=float))
    return _MERCATOR_RADIUS * lon, _MERCATOR_RADIUS * np.log(np.tan(np.pi / 4 + lat / 2))


def earth_locations(subarray):
    """(lon, lat, height) in deg, deg, m of the telescopes of a subarray, None if its location is unknown"""
    try:
        locations = subarray.tel_earth_locations
        geodetic = [locations[tel_id].to_geodetic() for tel_id in subarray.tel_ids]
    except Exception:
        return None
    lon = np.array([g.lon.deg for g in geodetic])
    lat = np.array([g.lat.deg for g in geodetic])
    height = np.array([g.height.to_value("m") for g in geodetic])
    if not (np.all(np.isfinite(lon)) and np.all(np.isfinite(lat)) and np.all(np.abs(lat) < 85)):
        return None
    return lon, lat, height


class ArrayMapPanel:
    """
    Telescopes of a subarray on an OpenStreetMap map, at their Earth location (the reference
    location of the subarray and the positions of the telescopes), with the same interactions as
    `ArrayPanel`. Use `earth_locations` to know whether the subarray has a location.
    """

    def __init__(self, subarray, on_tel_click=None, width=640, height=560, tiles="OpenStreetMap Mapnik",
                 colors=None):
        self._colors = colors or {}
        lon, lat, height_m = earth_locations(subarray)
        self.tel_ids = [int(t) for t in subarray.tel_ids]
        x, y = web_mercator(lon, lat)
        # telescope size on the map: mirror radius (the scale of the projection is 1 / cos(lat))
        radius = np.array([np.sqrt(subarray.tel[t].optics.mirror_area.to_value("m2") / np.pi) for t in self.tel_ids])
        radius = radius / np.cos(np.deg2rad(lat))
        margin = max(np.ptp(x), np.ptp(y), 200.0) * 1.0
        self.figure = figure(
            title=f"{subarray.name or 'Array'}: telescopes on OpenStreetMap",
            x_axis_type="mercator", y_axis_type="mercator", match_aspect=True,
            x_range=(x.mean() - margin, x.mean() + margin), y_range=(y.mean() - margin, y.mean() + margin),
            width=width, height=height, tools="wheel_zoom,box_zoom,reset,save", toolbar_location="above",
        )
        self.figure.add_tile(tiles, retina=True)
        self.source = ColumnDataSource(data=dict(
            x=x, y=y, radius=radius * 4, tel_id=self.tel_ids, label=[f"TEL {t}" for t in self.tel_ids],
            type=[str(subarray.tel[t]) for t in self.tel_ids], lon=lon, lat=lat, height=height_m,
            color=[self._colors.get(t, "#1f77b4") for t in self.tel_ids],
        ))
        renderer = self.figure.circle(x="x", y="y", radius="radius", source=self.source, fill_color="color",
                                      line_color="white", line_width=2, fill_alpha=0.9)
        self.figure.add_tools(HoverTool(renderers=[renderer], tooltips=[
            ("telescope", "@label"), ("type", "@type"), ("longitude", "@lon{0.00000} deg"),
            ("latitude", "@lat{0.00000} deg"), ("height", "@height{0.0} m"),
        ]))
        self.figure.add_layout(LabelSet(x="x", y="y", text="label", source=self.source, y_offset=14,
                                        text_align="center", text_font_size="11pt", text_font_style="bold",
                                        text_color="#111111", background_fill_color="white",
                                        background_fill_alpha=0.7))
        self._x, self._y, self._radius = x, y, radius * 4
        self._ring = ColumnDataSource(data=dict(x=[], y=[], radius=[], color=[]))
        self.figure.circle(x="x", y="y", radius="radius", source=self._ring, fill_color=None,
                           line_color="color", line_width=4)
        self._active = ColumnDataSource(data=dict(x=[], y=[]))
        self.figure.scatter(x="x", y="y", source=self._active, size=10, marker="circle",
                            fill_color=ACTIVE_COLOR, line_color="white")
        self._on_tel_click = on_tel_click
        if on_tel_click is not None:
            self.figure.add_tools(TapTool(renderers=[renderer]))
            self.source.selected.on_change("indices", self._clicked)
        self.layout = self.figure

    def _clicked(self, attr, old, new):
        """A telescope was clicked: ``on_tel_click(tel_id)`` (the click selection is not kept)"""
        if new:
            self._on_tel_click(self.tel_ids[new[0]])
            # the selection is shown by the ring
            self.source.selected.indices = []

    def set_selected(self, tel_ids):
        """Ring of the color of each selected telescope"""
        indices = [self.tel_ids.index(t) for t in tel_ids if t in self.tel_ids]
        data = dict(x=self._x[indices], y=self._y[indices], radius=self._radius[indices] * 1.4,
                    color=[self._colors.get(self.tel_ids[i], SELECTED_COLOR) for i in indices])
        if any(not np.array_equal(data[k], self._ring.data.get(k, [])) for k in ("x", "y")):
            self._ring.data = data

    set_active = ArrayPanel.set_active
