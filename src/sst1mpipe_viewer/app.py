"""Bokeh document of a session of the viewer: the header (telescope selection, navigation) and the pages"""

import base64
import functools
import time
from importlib.resources import files

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Button, Div, Select, TabPanel, Tabs, Toggle
from ctapipe.coordinates import TelescopeFrame

from .pages import DL1EventPage, DL1StatisticsPage, OverviewPage, WaveformPage

__all__ = ["ViewerSession", "make_document"]

#: background of the banner, the logo is white
BANNER_COLOR = "#282828"
#: period of the refresh of the displays (ms)
REFRESH_PERIOD = 1000
#: minimum time between two refreshes of the statistics page for new data (s)
STATISTICS_PERIOD = 2.0


@functools.cache
def _logo_html(height=56):
    data = base64.b64encode((files("sst1mpipe_viewer") / "resources" / "logo.png").read_bytes()).decode()
    return f"<img src='data:image/png;base64,{data}' style='height: {height}px' alt='SST-1M'>"


class ViewerSession:
    """
    State of a browser session: the selected telescope, the displayed event (``follow``
    the last one or a chosen one) and the selected pixels, shared by all the pages. The
    pages are refreshed periodically, only the visible one and only if something changed.
    """

    def __init__(self, store, doc=None, refresh_period=REFRESH_PERIOD, statistics_period=STATISTICS_PERIOD):
        self.store = store
        self.doc = doc
        tel_ids = store.tel_ids
        self.tel_id = tel_ids[0] if tel_ids else None
        self.follow = True
        self._event_key = None
        self.selected_pixels = []
        self._geometries = {}
        self._versions = {}  # page -> version of the store at its last refresh
        self._refresh_times = {}  # page -> time of its last refresh
        self._dirty = True

        self.tel_select = Select(title="Telescope", value=self._tel_label(self.tel_id),
                                 options=[self._tel_label(t) for t in tel_ids], width=110)
        self.tel_select.on_change("value", lambda attr, old, new: self.set_tel(self._tel_from_label(new)))
        self.live = Toggle(label="Live", active=True, button_type="success", width=70)
        self.live.on_change("active", lambda attr, old, new: self.set_follow(new))
        self.prev_button = Button(label="◀ Prev", width=75)
        self.next_button = Button(label="Next ▶", width=75)
        self.prev_button.on_click(lambda: self.step(-1))
        self.next_button.on_click(lambda: self.step(+1))
        self.clear_pixels = Button(label="Clear pixel selection", width=150)
        self.clear_pixels.on_click(lambda: self.set_selected_pixels([]))
        self.status = Div(text="", styles={"font-size": "10pt", "color": "#444"}, width=1400, height=36)

        self.pages = [
            OverviewPage(self),
            WaveformPage(self, "r0"),
            WaveformPage(self, "r1"),
            WaveformPage(self, "dl0"),
            DL1EventPage(self),
            DL1StatisticsPage(self),
        ]
        # every refresh of the many figures of the statistics page lays the page out again
        self.pages[-1].min_interval = statistics_period
        self.tabs = Tabs(tabs=[TabPanel(child=page.layout, title=page.title) for page in self.pages])
        self.tabs.on_change("active", lambda attr, old, new: self.request_refresh())

        # the SST-1M logo (from sst1m.space) is white: it is shown on a dark banner
        banner = Div(
            text=(
                f"<div style='display: flex; align-items: center; gap: 24px; padding: 10px 18px;"
                f" background: {BANNER_COLOR}; border-radius: 4px'>{_logo_html()}"
                "<span style='font-size: 22pt; font-weight: 600; color: white'>Event Viewer</span></div>"
            ),
            width=1400, height=80,
        )
        navigation = row(self.tel_select, column(Div(text=""), row(self.live, self.prev_button, self.next_button,
                                                                   self.clear_pixels)))
        self.layout = column(banner, navigation, self.status, self.tabs)

        if doc is not None:
            doc.title = "SST-1M Event Viewer"
            doc.add_root(self.layout)
            doc.add_periodic_callback(self.tick, refresh_period)
        self.tick()

    # ------------------------------------------------------------ telescope
    @staticmethod
    def _tel_label(tel_id):
        return "" if tel_id is None else f"TEL {tel_id}"

    @staticmethod
    def _tel_from_label(label):
        return int(label.split()[-1]) if label else None

    def set_tel(self, tel_id):
        if tel_id == self.tel_id:
            return
        self.tel_id = tel_id
        self._event_key = None
        self.selected_pixels = []
        label = self._tel_label(tel_id)
        if label not in self.tel_select.options:
            self.tel_select.options = [*self.tel_select.options, label]
        self.tel_select.value = label
        self.request_refresh()

    def geometry(self, tel_id=None):
        """Camera geometry of a telescope (the selected one by default) in the TelescopeFrame"""
        tel_id = self.tel_id if tel_id is None else tel_id
        subarray = self.store.subarray
        if subarray is None or tel_id not in subarray.tel:
            return None
        key = (id(subarray), tel_id)
        if key not in self._geometries:
            self._geometries[key] = subarray.tel[tel_id].camera.geometry.transform_to(TelescopeFrame())
        return self._geometries[key]

    # ---------------------------------------------------------------- event
    def event_key(self, kind=None, predicate=None):
        """
        Key of the displayed event: if following, the last one with data of ``kind``
        (satisfying ``predicate(row)`` if given), else the chosen one.
        """
        if self.tel_id is None:
            return None
        if not self.follow:
            return self._event_key
        if predicate is not None:
            return self.store.find_latest_key(self.tel_id, kind, predicate)
        return self.store.latest_key(self.tel_id, kind)

    def set_follow(self, follow):
        self.follow = bool(follow)
        if self.live.active != self.follow:
            self.live.active = self.follow
        if self.follow:
            self._event_key = None
        elif self._event_key is None:
            self._event_key = self.store.latest_key(self.tel_id)
        self.request_refresh()

    def step(self, offset):
        """Show the previous (-1) or next (+1) event of the telescope"""
        keys = self.store.event_keys(self.tel_id)
        if not keys:
            return
        current = self._event_key if not self.follow else self.store.latest_key(self.tel_id)
        index = keys.index(current) if current in keys else len(keys) - 1
        self._event_key = keys[max(0, min(len(keys) - 1, index + offset))]
        self.set_follow(False)

    # --------------------------------------------------------------- pixels
    def set_selected_pixels(self, pixels):
        pixels = [int(p) for p in pixels]
        if pixels == self.selected_pixels:
            return
        self.selected_pixels = pixels
        self.request_refresh()

    # -------------------------------------------------------------- refresh
    def request_refresh(self):
        self._dirty = True

    @property
    def active_page(self):
        return self.pages[self.tabs.active]

    def tick(self):
        """
        Periodic update: telescopes, status and the visible page, at once after an action of
        the user, for new data at most every ``page.min_interval`` seconds.
        """
        tel_ids = self.store.tel_ids
        options = [self._tel_label(t) for t in tel_ids]
        if options != self.tel_select.options:
            self.tel_select.options = options
        if self.tel_id is None and tel_ids:
            self.set_tel(tel_ids[0])
        status = self._status_text()
        if status != self.status.text:
            self.status.text = status
        page = self.active_page
        version = self.store.version
        now = time.monotonic()
        if not self._dirty:
            if self._versions.get(page) == version:
                return
            if now - self._refresh_times.get(page, -np.inf) < page.min_interval:
                return
        self._dirty = False
        self._versions[page] = version
        self._refresh_times[page] = now
        page.refresh()

    def _status_text(self):
        # changes only with the actions of the user: changing a Div lays out the whole page again
        # (slow), the rates are in the table of the Overview page
        source = self.store.source_description or "no source"
        mode = "following the last event" if self.follow else "browsing (press Live to follow the last event)"
        pixels = ", ".join(str(p) for p in self.selected_pixels) or "none"
        return (
            f"<b>Source</b>: {source} &nbsp;|&nbsp; <b>TEL {self.tel_id}</b> &nbsp;|&nbsp; {mode}"
            f" &nbsp;|&nbsp; <b>selected pixels</b>: {pixels}"
        )


def make_document(store, doc, **kwargs):
    """Fill a bokeh document with a viewer session on ``store`` (bokeh application handler)"""
    ViewerSession(store, doc, **kwargs)
