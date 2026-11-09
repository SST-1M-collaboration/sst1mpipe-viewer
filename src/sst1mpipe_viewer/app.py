"""
Bokeh documents of the viewer: one web page per data level (Array, R0, R1, DL0, DL1 Event,
DL1 Statistics, DL2 Event, DL2 Statistics), with a header (navigation, displayed events).

The pages opened by a browser share a `UserState`: the selected telescopes (chosen in the Array
page), the displayed event of each telescope and the selected pixels. It is found by the client id
of the links of the navigation (``?c=<id>``), so that going from a page to another keeps the
context. The pages show the data of all the selected telescopes, each telescope with its color
(`sst1mpipe_viewer.colors`).
"""

import base64
import functools
import threading
import time
import uuid
from importlib.resources import files

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Button, Div, TextInput, Toggle
from ctapipe.coordinates import TelescopeFrame

from .colors import telescope_color
from .components import CameraPanel
from .pages import ArrayPage, ImageEventPage, StatisticsPage, WaveformPage

__all__ = ["PAGES", "StateRegistry", "UserState", "ViewerSession", "make_document"]

#: background of the banner, the logo is white
BANNER_COLOR = "#282828"
#: period of the check for changes (ms): new data, actions in the other pages of the browser
REFRESH_PERIOD = 250
#: minimum time between two refreshes of an event page for new data (s): at high rates, the
#: events in between are not displayed (they are all in the statistics)
EVENT_PERIOD = 0.5
#: minimum time between two refreshes of the statistics page for new data (s)
STATISTICS_PERIOD = 2.0
#: colormaps of the cameras and of the per pixel fields, color scale (set when the viewer starts)
COLORMAP, FIELD_COLORMAP, COLOR_SCALE = "inferno", "viridis", "lin"

#: pages: name -> (URL path, title, page factory)
PAGES = {
    "array": ("/", "Array", ArrayPage),
    "r0": ("/r0", "R0", lambda session: WaveformPage(session, "r0")),
    "r1": ("/r1", "R1", lambda session: WaveformPage(session, "r1")),
    "dl0": ("/dl0", "DL0", lambda session: WaveformPage(session, "dl0")),
    "dl1": ("/dl1", "DL1 Event", lambda session: ImageEventPage(session, "dl1")),
    "dl1_statistics": ("/dl1_statistics", "DL1 Statistics", lambda session: StatisticsPage(session, "dl1")),
    "dl2": ("/dl2", "DL2 Event", lambda session: ImageEventPage(session, "dl2")),
    "dl2_statistics": ("/dl2_statistics", "DL2 Statistics", lambda session: StatisticsPage(session, "dl2")),
}

#: pages of accumulated statistics (refreshed less often: many figures)
STATISTICS_PAGES = ("dl1_statistics", "dl2_statistics")


@functools.cache
def _logo_html(height=56):
    """HTML ``<img>`` of the SST-1M logo (white, for the dark banner), embedded in the page"""
    data = base64.b64encode((files("sst1mpipe_viewer") / "resources" / "logo.png").read_bytes()).decode()
    return f"<img src='data:image/png;base64,{data}' style='height: {height}px' alt='SST-1M'>"


class UserState:
    """
    Navigation state of a browser, shared by all its pages.

    Attributes
    ----------
    tel_ids : list
        The selected telescopes (chosen in the Array page).
    follow : bool
        True: the pages show the last events received (Live mode). False: they show the events
        chosen in ``event_keys``.
    event_keys : dict
        ``{tel_id: (obs_id, event_id)}``, the displayed event of each telescope when not following.
    auto_browse : bool
        Go to the first events of the file as soon as they are loaded.
    selected_pixels : dict
        ``{tel_id: [pixel, ...]}``, the selected pixels of each telescope.
    goto_error : str or None
        Error of the last "Event id" request, shown in the status line.
    version : int
        Incremented at each change (`changed`): the other pages of the browser follow it.
    """

    def __init__(self, store):
        self.tel_ids = list(store.tel_ids)  # all the telescopes are selected at first
        # data pushed event by event (a stream): follow the last events; tables only (a file):
        # show the first event of each telescope
        first = {tel_id: keys[0] for tel_id in self.tel_ids if (keys := store.event_keys(tel_id))}
        self.follow = store.has_event_data or not first
        self.event_keys = {} if self.follow else first
        # without data yet: go to the first events if the data come as tables (a file being loaded)
        self.auto_browse = self.follow and not store.has_event_data
        self.selected_pixels = {}  # {tel_id: [pixel, ...]}
        self.goto_error = None
        self.version = 0

    def changed(self):
        """Mark a change of the state: the pages of the browser are refreshed"""
        self.version += 1


class StateRegistry:
    """The `UserState` of each client id"""

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()

    def get(self, client_id, store):
        """The state of a client id (created at the first use)"""
        with self._lock:
            if client_id not in self._states:
                self._states[client_id] = UserState(store)
            return self._states[client_id]


class ViewerSession:
    """
    A page of the viewer opened in a browser: the header (logo, navigation between the pages,
    Live / Prev / Next / Event id, status line) and the page of a data level (`PAGES`).

    The page is refreshed only if something changed: at once after an action of the user (here or
    in another page of the same browser), and for new data at most every ``event_period`` seconds
    (``statistics_period`` for the statistics pages). All the changes of a refresh are sent to the
    browser in a single message.

    Parameters
    ----------
    store : ViewerStore
        The data shown.
    doc : bokeh.document.Document or None
        The document of the browser (None in the tests).
    page : str
        Name of the page in `PAGES`.
    state : UserState or None
        The state shared by the pages of the browser (a new one if None).
    client_id : str or None
        Id of the browser, in the links of the navigation.
    refresh_period : int
        Period of the check for changes (ms).
    statistics_period, event_period : float
        Minimum time between two refreshes for new data (s), of the statistics pages and of the
        other pages: at high rates the events in between are not drawn (they are all counted in
        the statistics).
    colormap, field_colormap, color_scale : str
        Colormaps of the data cameras and of the per pixel fields, ``"lin"`` or ``"log"`` scale.
    """

    def __init__(self, store, doc=None, page="array", state=None, client_id=None,
                 refresh_period=REFRESH_PERIOD, statistics_period=STATISTICS_PERIOD, event_period=EVENT_PERIOD,
                 colormap=COLORMAP, field_colormap=FIELD_COLORMAP, color_scale=COLOR_SCALE):
        self.store = store
        self.doc = doc
        self.client_id = client_id or uuid.uuid4().hex[:12]
        self.state = state if state is not None else UserState(store)
        self.page_name = page
        self.colormap, self.field_colormap, self.color_scale = colormap, field_colormap, color_scale
        self._geometries = {}
        self._store_version = None
        self._state_version = None
        self._refresh_time = -np.inf
        self._dirty = True
        self._in_tick = False
        self._tick_scheduled = False

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
        self.clear_pixels.on_click(self.clear_selected_pixels)
        self.status = Div(text="", styles={"font-size": "10pt", "color": "#444"}, width=1400, height=40)

        _, title, factory = PAGES[page]
        self.page = factory(self)
        # every refresh of the many figures of the statistics page lays the page out again
        self.page.min_interval = statistics_period if page in STATISTICS_PAGES else event_period

        # the SST-1M logo (from sst1m.space) is white: it is shown on a dark banner
        banner = Div(
            text=(
                f"<div style='display: flex; align-items: center; gap: 24px; padding: 10px 18px;"
                f" background: {BANNER_COLOR}; border-radius: 4px'>{_logo_html()}"
                "<span style='font-size: 22pt; font-weight: 600; color: white'>Event Viewer</span></div>"
            ),
            width=1400, height=80,
        )
        controls = row(column(Div(text=""), row(self.live, self.prev_button, self.next_button)),
                       self.event_input, column(Div(text=""), self.clear_pixels))
        self.layout = column(banner, Div(text=self._navigation_html(), width=1400, height=34), controls,
                             self.status, self.page.layout)

        # the first refresh is done before the page is in the document: the changes of the models
        # of a document are slow (bokeh indexes all its models again when references change), and
        # it is in the initial document sent to the browser
        self.tick()
        if doc is not None:
            doc.title = f"SST-1M Event Viewer – {title}"
            doc.add_root(self.layout)
            doc.add_periodic_callback(self.tick, refresh_period)

    @property
    def pages(self):
        """The page of the session, in a list (as the tests use it)"""
        return [self.page]

    def _navigation_html(self):
        """Links to the pages, with the client id (the pages share the state of the browser)"""
        links = []
        for name, (path, title, _) in PAGES.items():
            style = ("background: #282828; color: white;" if name == self.page_name
                     else "background: #eceff1; color: #263238;")
            links.append(f"<a href='{path}?c={self.client_id}' style='{style} padding: 6px 14px;"
                         f" border-radius: 4px; text-decoration: none; font-weight: 600'>{title}</a>")
        return f"<div style='display: flex; gap: 8px; font-size: 11pt'>{''.join(links)}</div>"

    def camera_panel(self, **kwargs):
        """Camera with the colormap and the color scale of the viewer"""
        options = dict(cmap=self.colormap, scale=self.color_scale)
        options.update(kwargs)
        return CameraPanel(**options)

    # ---------------------------------------------------- state of the user
    @property
    def tel_ids(self):
        """The selected telescopes, sorted"""
        return sorted(self.state.tel_ids)

    @property
    def all_tel_ids(self):
        """All the telescopes (of the subarray and of the data), selected or not"""
        return list(self.store.tel_ids)

    def color(self, tel_id):
        """Color of a telescope, the same in all the pages"""
        return telescope_color(tel_id, self.all_tel_ids)

    @property
    def follow(self):
        """Whether the pages follow the last events received (Live mode)"""
        return self.state.follow

    def selected_pixels(self, tel_id):
        """The selected pixels of a telescope"""
        return self.state.selected_pixels.get(tel_id, [])

    def _changed(self):
        """Mark a change of the state and refresh this page at once"""
        self.state.changed()
        self.request_refresh()

    # ----------------------------------------------------------- telescopes
    def set_tels(self, tel_ids):
        """Select telescopes (the pages show their data)"""
        state = self.state
        tel_ids = sorted({int(t) for t in tel_ids})
        if tel_ids == sorted(state.tel_ids):
            return
        state.tel_ids = tel_ids
        state.goto_error = None
        if not state.follow:
            # the telescopes newly selected show their first event
            for tel_id in tel_ids:
                if tel_id not in state.event_keys and (keys := self.store.event_keys(tel_id)):
                    state.event_keys[tel_id] = keys[0]
        self._changed()

    def toggle_tel(self, tel_id):
        """Select or unselect a telescope"""
        selected = set(self.state.tel_ids)
        self.set_tels(selected - {tel_id} if tel_id in selected else selected | {tel_id})

    def geometry(self, tel_id):
        """Camera geometry of a telescope in the TelescopeFrame (None if unknown)"""
        subarray = self.store.subarray
        if subarray is None or tel_id is None or tel_id not in subarray.tel:
            return None
        key = (id(subarray), tel_id)
        if key not in self._geometries:
            self._geometries[key] = subarray.tel[tel_id].camera.geometry.transform_to(TelescopeFrame())
        return self._geometries[key]

    # ---------------------------------------------------------------- event
    def event_key(self, tel_id, kind=None, finite_column=None):
        """
        Key of the displayed event of a telescope: if following, the last one with data of
        ``kind`` (with a finite ``finite_column`` if given, e.g. the events surviving the cleaning),
        else the chosen one.
        """
        if not self.follow:
            return self.state.event_keys.get(tel_id)
        if finite_column is not None:
            return self.store.find_latest_key(tel_id, kind, finite_column)
        return self.store.latest_key(tel_id, kind)

    def go_to(self, value):
        """
        Show the event ``value`` of each selected telescope: an event_id, or ``#index`` for the
        index of the event (from 0) in the events of each telescope. Unknown values are ignored.
        """
        value = value.strip()
        if not value or not self.tel_ids:
            return
        found = {}
        for tel_id in self.tel_ids:
            keys = self.store.event_keys(tel_id)
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
                found[tel_id] = key
        if found:
            self._browse()
            self.state.event_keys.update(found)
            missing = [t for t in self.tel_ids if t not in found]
            self.set_follow(False)
            if missing:
                self.state.goto_error = f"no event {value} for " + ", ".join(f"TEL {t}" for t in missing)
        else:
            self.state.goto_error = f"no event {value}"
            self._changed()

    def _browse(self):
        """Displayed events when leaving the Live mode: the last events"""
        state = self.state
        if state.follow:
            state.event_keys = {t: k for t in self.all_tel_ids if (k := self.store.latest_key(t)) is not None}
            state.follow = False

    def _live_clicked(self, active):
        """The Live button was clicked (or changed by `_update_header`)"""
        if bool(active) == self.follow:
            return  # set by _update_header
        self.state.auto_browse = False
        self.set_follow(active)

    def set_follow(self, follow):
        """Follow the last events (Live mode), or browse the events from the last ones"""
        state = self.state
        state.goto_error = None
        if not follow:
            self._browse()
        state.follow = bool(follow)
        if state.follow:
            state.event_keys = {}
        self._update_header()
        self._changed()

    def step(self, offset, tel_ids=None):
        """Show the previous (-1) or next (+1) event of each selected telescope (or of ``tel_ids``)"""
        self._browse()
        state = self.state
        for tel_id in self.tel_ids if tel_ids is None else tel_ids:
            keys = self.store.event_keys(tel_id)
            if not keys:
                continue
            current = state.event_keys.get(tel_id)
            index = keys.index(current) if current in keys else len(keys) - 1
            state.event_keys[tel_id] = keys[max(0, min(len(keys) - 1, index + offset))]
        self.set_follow(False)

    # --------------------------------------------------------------- pixels
    def set_selected_pixels(self, pixels, tel_id):
        """Select pixels of a telescope (each telescope has its own selection)"""
        pixels = [int(p) for p in pixels]
        if pixels == self.selected_pixels(tel_id):
            return
        self.state.selected_pixels[tel_id] = pixels
        self._changed()

    def pixel_click(self, tel_id):
        """Callback of a click on the pixels of a camera of a telescope"""
        return lambda pixels: self.set_selected_pixels(pixels, tel_id)

    def clear_selected_pixels(self):
        """Unselect the pixels of all the telescopes"""
        if any(self.state.selected_pixels.values()):
            self.state.selected_pixels = {}
            self._changed()

    # -------------------------------------------------------------- refresh
    def request_refresh(self):
        """Refresh the page: at once after an action of the user (not at the next periodic check)"""
        self._dirty = True
        if self.doc is not None and not self._in_tick and not self._tick_scheduled:
            self._tick_scheduled = True
            self.doc.add_next_tick_callback(self._scheduled_tick)

    def _scheduled_tick(self):
        """Refresh asked by `request_refresh`"""
        self._tick_scheduled = False
        self.tick()

    def _update_header(self):
        """Widgets of the header from the state (changed here or in another page of the browser)"""
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
        self._in_tick = True
        try:
            self._tick()
        finally:
            self._in_tick = False
            if self.doc is not None:
                self.doc.unhold()

    def _tick(self):
        """Refresh of `tick` (see there), without the bokeh hold"""
        state = self.state
        if not state.tel_ids and self.store.tel_ids and state.version == 0:
            state.tel_ids = list(self.store.tel_ids)  # telescopes known after the state was created
        self._auto_browse()
        # an action of the user in this page or in another page of the browser
        if state.version != self._state_version:
            self._state_version = state.version
            self._update_header()
            self._dirty = True
        status = self._status_text()
        if status != self.status.text:
            self.status.text = status
        if self._needs_refresh():
            self._dirty = False
            self._store_version = self.store.version
            self._refresh_time = time.monotonic()
            self.page.refresh()

    def _auto_browse(self):
        """A file being loaded: show its first events as soon as they are there"""
        state, store = self.state, self.store
        if not state.auto_browse:
            return
        if store.has_event_data:  # a stream, not a file: the Live mode is kept
            state.auto_browse = False
            return
        first = {t: keys[0] for t in store.tel_ids if (keys := store.event_keys(t))}
        if first:
            state.auto_browse = False
            state.follow = False
            state.event_keys = first
            state.changed()

    def _needs_refresh(self):
        """Whether the page must be refreshed: an action of the user, or new data (not too often)"""
        if self._dirty:
            return True
        if self._store_version == self.store.version:
            return False
        return time.monotonic() - self._refresh_time >= self.page.min_interval

    def _status_text(self):
        """Text of the status line: source, displayed event and selected pixels of each telescope, mode"""
        # it changes only with the actions of the user (changing a Div lays out the whole page
        # again, slow): the rates are in the Array page
        state = self.state
        source = self.store.source_description or "no source"
        telescopes = []
        for tel_id in self.tel_ids:
            label = f"<b style='color: {self.color(tel_id)}'>TEL {tel_id}</b>"
            if not state.follow:
                key = state.event_keys.get(tel_id)
                position, n_events = self.store.event_position(tel_id, key)
                event = f"event_id {key[1]}" if key else "no event"
                label += f" {event} ({'?' if position is None else position + 1} / {n_events})"
            pixels = self.selected_pixels(tel_id)
            if len(pixels) > 10:
                label += f" [{len(pixels)} pixels]"
            elif pixels:
                label += f" [pixels {', '.join(str(p) for p in pixels)}]"
            telescopes.append(label)
        mode = "following the last events" if state.follow else "browsing"
        if state.goto_error:
            mode += f" &nbsp;<span style='color: #c62828'>{state.goto_error}</span>"
        return (
            f"<b>Source</b>: {source} &nbsp;|&nbsp; {' &nbsp; '.join(telescopes) or 'no telescope selected'}"
            f" &nbsp;|&nbsp; {mode}"
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


def make_document(store, doc, page="array", registry=None, **kwargs):
    """Fill a bokeh document with a page of the viewer on ``store`` (bokeh application handler)"""
    client_id = _client_id(doc) or uuid.uuid4().hex[:12]
    state = registry.get(client_id, store) if registry is not None else None
    ViewerSession(store, doc, page=page, state=state, client_id=client_id, **kwargs)
