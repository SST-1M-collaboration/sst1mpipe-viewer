"""
Bokeh documents of the viewer: one web page per data level (Overview, R0, R1, DL0, DL1 Event,
DL1 Statistics), with a header (navigation, telescope, event, pixel selection).

The pages opened by a browser share a `UserState` (selected telescope, displayed event, selected
pixels): it is found by the client id of the links of the navigation (``?c=<id>``), so that going
from a page to another keeps the context.
"""

import base64
import functools
import threading
import time
import uuid
from importlib.resources import files

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Button, Div, Select, TextInput, Toggle
from ctapipe.coordinates import TelescopeFrame

from .pages import DL1EventPage, DL1StatisticsPage, OverviewPage, WaveformPage

__all__ = ["PAGES", "StateRegistry", "UserState", "ViewerSession", "make_document"]

#: background of the banner, the logo is white
BANNER_COLOR = "#282828"
#: period of the refresh of the displays (ms)
REFRESH_PERIOD = 1000
#: minimum time between two refreshes of the statistics page for new data (s)
STATISTICS_PERIOD = 2.0

#: pages: name -> (URL path, title, page factory)
PAGES = {
    "overview": ("/", "Overview", OverviewPage),
    "r0": ("/r0", "R0", lambda session: WaveformPage(session, "r0")),
    "r1": ("/r1", "R1", lambda session: WaveformPage(session, "r1")),
    "dl0": ("/dl0", "DL0", lambda session: WaveformPage(session, "dl0")),
    "dl1": ("/dl1", "DL1 Event", DL1EventPage),
    "statistics": ("/statistics", "DL1 Statistics", DL1StatisticsPage),
}


@functools.cache
def _logo_html(height=56):
    data = base64.b64encode((files("sst1mpipe_viewer") / "resources" / "logo.png").read_bytes()).decode()
    return f"<img src='data:image/png;base64,{data}' style='height: {height}px' alt='SST-1M'>"


class UserState:
    """
    Navigation state of a browser, shared by its pages: the selected telescope, the displayed
    event (``follow`` the last one or ``event_key``) and the selected pixels. ``version`` is
    incremented at each change, so that the other pages of the browser follow it.
    """

    def __init__(self, store):
        tel_ids = store.tel_ids
        self.tel_id = tel_ids[0] if tel_ids else None
        # data pushed event by event (a stream): follow the last event; tables only (a file):
        # show its first event
        keys = store.event_keys(self.tel_id) if self.tel_id is not None else []
        self.follow = store.has_event_data or not keys
        self.event_key = None if self.follow else keys[0]
        # without data yet: go to the first event if the data come as tables (a file being loaded)
        self.auto_browse = self.follow and not store.has_event_data
        self.selected_pixels = []
        self.goto_error = None
        self.version = 0

    def changed(self):
        self.version += 1


class StateRegistry:
    """The `UserState` of each client id"""

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()

    def get(self, client_id, store):
        with self._lock:
            if client_id not in self._states:
                self._states[client_id] = UserState(store)
            return self._states[client_id]


class ViewerSession:
    """
    A page of the viewer in a browser: the header (navigation between the pages, telescope,
    event, pixel selection) and the page of a data level. The page is refreshed periodically,
    only if something changed (new data, an action of the user here or in another page of the
    browser), all its changes being sent to the browser in a single message.
    """

    def __init__(self, store, doc=None, page="overview", state=None, client_id=None,
                 refresh_period=REFRESH_PERIOD, statistics_period=STATISTICS_PERIOD):
        self.store = store
        self.doc = doc
        self.client_id = client_id or uuid.uuid4().hex[:12]
        self.state = state if state is not None else UserState(store)
        self.page_name = page
        self._geometries = {}
        self._store_version = None
        self._state_version = None
        self._refresh_time = -np.inf
        self._dirty = True

        tel_ids = store.tel_ids
        self.tel_select = Select(title="Telescope", value=self._tel_label(self.tel_id),
                                 options=[self._tel_label(t) for t in tel_ids], width=110)
        self.tel_select.on_change("value", lambda attr, old, new: self.set_tel(self._tel_from_label(new)))
        self.live = Toggle(label="Live", active=self.follow, button_type="success" if self.follow else "default",
                           width=70)
        self.live.on_change("active", lambda attr, old, new: self._live_clicked(new))
        self.prev_button = Button(label="◀ Prev", width=75)
        self.next_button = Button(label="Next ▶", width=75)
        self.prev_button.on_click(lambda: self.step(-1))
        self.next_button.on_click(lambda: self.step(+1))
        self.event_input = TextInput(title="Event id", value="", width=130, placeholder="event_id or #index")
        self.event_input.on_change("value", lambda attr, old, new: self.go_to(new))
        self.clear_pixels = Button(label="Clear pixel selection", width=150)
        self.clear_pixels.on_click(lambda: self.set_selected_pixels([]))
        self.status = Div(text="", styles={"font-size": "10pt", "color": "#444"}, width=1400, height=36)

        _, title, factory = PAGES[page]
        self.page = factory(self)
        if page == "statistics":
            # every refresh of the many figures of the statistics page lays the page out again
            self.page.min_interval = statistics_period

        # the SST-1M logo (from sst1m.space) is white: it is shown on a dark banner
        banner = Div(
            text=(
                f"<div style='display: flex; align-items: center; gap: 24px; padding: 10px 18px;"
                f" background: {BANNER_COLOR}; border-radius: 4px'>{_logo_html()}"
                "<span style='font-size: 22pt; font-weight: 600; color: white'>Event Viewer</span></div>"
            ),
            width=1400, height=80,
        )
        controls = row(self.tel_select, column(Div(text=""), row(self.live, self.prev_button, self.next_button)),
                       self.event_input, column(Div(text=""), self.clear_pixels))
        self.layout = column(banner, Div(text=self._navigation_html(), width=1400, height=34), controls,
                             self.status, self.page.layout)

        if doc is not None:
            doc.title = f"SST-1M Event Viewer – {title}"
            doc.add_root(self.layout)
            doc.add_periodic_callback(self.tick, refresh_period)
        # the first refresh is in the initial document sent to the browser
        self.tick()

    @property
    def pages(self):
        return [self.page]

    def _navigation_html(self):
        links = []
        for name, (path, title, _) in PAGES.items():
            style = ("background: #282828; color: white;" if name == self.page_name
                     else "background: #eceff1; color: #263238;")
            links.append(f"<a href='{path}?c={self.client_id}' style='{style} padding: 6px 14px;"
                         f" border-radius: 4px; text-decoration: none; font-weight: 600'>{title}</a>")
        return f"<div style='display: flex; gap: 8px; font-size: 11pt'>{''.join(links)}</div>"

    # ---------------------------------------------------- state of the user
    @property
    def tel_id(self):
        return self.state.tel_id

    @property
    def follow(self):
        return self.state.follow

    @property
    def selected_pixels(self):
        return self.state.selected_pixels

    @property
    def _event_key(self):
        return self.state.event_key

    def _changed(self):
        self.state.changed()
        self.request_refresh()

    # ------------------------------------------------------------ telescope
    @staticmethod
    def _tel_label(tel_id):
        return "" if tel_id is None else f"TEL {tel_id}"

    @staticmethod
    def _tel_from_label(label):
        return int(label.split()[-1]) if label else None

    def set_tel(self, tel_id):
        state = self.state
        if tel_id == state.tel_id:
            return
        state.tel_id = tel_id
        state.goto_error = None
        keys = self.store.event_keys(tel_id) if tel_id is not None else []
        state.event_key = None if state.follow or not keys else keys[0]
        state.selected_pixels = []
        self._update_header()
        self._changed()

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
    def event_key(self, kind=None, finite_column=None):
        """
        Key of the displayed event: if following, the last one with data of ``kind`` (with a
        finite ``finite_column`` if given, e.g. the events surviving the cleaning), else the
        chosen one.
        """
        if self.tel_id is None:
            return None
        if not self.follow:
            return self.state.event_key
        if finite_column is not None:
            return self.store.find_latest_key(self.tel_id, kind, finite_column)
        return self.store.latest_key(self.tel_id, kind)

    def go_to(self, value):
        """
        Show the event ``value`` of the telescope: an event_id, or ``#index`` for the index of
        the event (from 0) in the events of the telescope. Unknown values are ignored.
        """
        value = value.strip()
        if not value or self.tel_id is None:
            return
        keys = self.store.event_keys(self.tel_id)
        key = None
        try:
            if value.startswith("#"):
                index = int(value[1:])
                key = keys[index] if -len(keys) <= index < len(keys) else None
            else:
                event_id = int(value)
                key = next((k for k in keys if k[1] == event_id), None)
        except ValueError:
            key = None
        if key is not None:
            self.state.event_key = key
            self.set_follow(False)
        else:
            self.state.goto_error = f"no event {value} for TEL {self.tel_id}"
            self._changed()

    def _live_clicked(self, active):
        if bool(active) == self.follow:
            return  # set by _update_header
        self.state.auto_browse = False
        self.set_follow(active)

    def set_follow(self, follow):
        state = self.state
        state.goto_error = None
        state.follow = bool(follow)
        if state.follow:
            state.event_key = None
        elif state.event_key is None:
            state.event_key = self.store.latest_key(self.tel_id)
        self._update_header()
        self._changed()

    def step(self, offset):
        """Show the previous (-1) or next (+1) event of the telescope"""
        keys = self.store.event_keys(self.tel_id)
        if not keys:
            return
        current = self.state.event_key if not self.follow else self.store.latest_key(self.tel_id)
        index = keys.index(current) if current in keys else len(keys) - 1
        self.state.event_key = keys[max(0, min(len(keys) - 1, index + offset))]
        self.set_follow(False)

    # --------------------------------------------------------------- pixels
    def set_selected_pixels(self, pixels):
        pixels = [int(p) for p in pixels]
        if pixels == self.state.selected_pixels:
            return
        self.state.selected_pixels = pixels
        self._changed()

    # -------------------------------------------------------------- refresh
    def request_refresh(self):
        self._dirty = True

    @property
    def active_page(self):
        return self.page

    def _update_header(self):
        """Widgets of the header from the state (changed here or in another page of the browser)"""
        label = self._tel_label(self.tel_id)
        if label not in self.tel_select.options:
            self.tel_select.options = [*self.tel_select.options, label]
        if self.tel_select.value != label:
            self.tel_select.value = label
        if self.live.active != self.follow:
            self.live.active = self.follow
        # green when following the last event
        self.live.button_type = "success" if self.follow else "default"

    def tick(self):
        """
        Periodic update of the page: at once after an action of the user (here or in another page
        of the browser), for new data at most every ``page.min_interval`` seconds. All the changes
        are sent to the browser in a single message, so that it lays the page out once.
        """
        if self.doc is not None:
            self.doc.hold("combine")
        try:
            self._tick()
        finally:
            if self.doc is not None:
                self.doc.unhold()

    def _tick(self):
        state, store = self.state, self.store
        tel_ids = store.tel_ids
        options = [self._tel_label(t) for t in tel_ids]
        if options != self.tel_select.options:
            self.tel_select.options = options
        if state.tel_id is None and tel_ids:
            self.set_tel(tel_ids[0])
        if state.auto_browse and state.tel_id is not None:
            if store.has_event_data:
                state.auto_browse = False
            else:
                keys = store.event_keys(state.tel_id)
                if keys:
                    state.auto_browse = False
                    state.event_key = keys[0]
                    self.set_follow(False)
        if state.version != self._state_version:
            self._state_version = state.version
            self._update_header()
            self._dirty = True
        status = self._status_text()
        if status != self.status.text:
            self.status.text = status
        page = self.page
        version = store.version
        now = time.monotonic()
        if not self._dirty:
            if self._store_version == version:
                return
            if now - self._refresh_time < page.min_interval:
                return
        self._dirty = False
        self._store_version = version
        self._refresh_time = now
        page.refresh()

    def _status_text(self):
        # changes only with the actions of the user: changing a Div lays out the whole page again
        # (slow), the rates are in the table of the Overview page
        state = self.state
        source = self.store.source_description or "no source"
        if state.follow:
            mode = "following the last event"
        else:
            position, n_events = self.store.event_position(state.tel_id, state.event_key)
            event = f"event_id {state.event_key[1]}" if state.event_key else "no event"
            mode = f"{event} ({'?' if position is None else position + 1} / {n_events})"
        if state.goto_error:
            mode += f" &nbsp;<span style='color: #c62828'>{state.goto_error}</span>"
        n_selected = len(state.selected_pixels)
        if n_selected > 10:
            pixels = f"{n_selected} pixels"
        else:
            pixels = ", ".join(str(p) for p in state.selected_pixels) or "none"
        return (
            f"<b>Source</b>: {source} &nbsp;|&nbsp; <b>TEL {state.tel_id}</b> &nbsp;|&nbsp; {mode}"
            f" &nbsp;|&nbsp; <b>selected pixels</b>: {pixels}"
        )


def _client_id(doc):
    """Client id of the URL of a document (``?c=<id>``), None if none"""
    try:
        values = doc.session_context.request.arguments.get("c")
    except AttributeError:
        return None
    if not values:
        return None
    value = values[0].decode() if isinstance(values[0], bytes) else str(values[0])
    return value if value.isalnum() and len(value) <= 64 else None


def make_document(store, doc, page="overview", registry=None, **kwargs):
    """Fill a bokeh document with a page of the viewer on ``store`` (bokeh application handler)"""
    client_id = _client_id(doc) or uuid.uuid4().hex[:12]
    state = registry.get(client_id, store) if registry is not None else None
    ViewerSession(store, doc, page=page, state=state, client_id=client_id, **kwargs)
