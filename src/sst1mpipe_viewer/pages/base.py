"""Base class of the pages of the viewer, and helpers shared by the pages"""

from astropy.time import Time
from bokeh.layouts import row
from bokeh.models import Button, Div
from ctapipe.containers import EventType

from ..components import RatePanel

__all__ = ["Page", "LevelRates", "message_div", "event_description", "telescope_header"]

#: names of the data levels in the titles
LEVEL_NAMES = {"r0": "R0", "r1": "R1", "dl0": "DL0", "dl1": "DL1", "dl2": "DL2", "trigger": "trigger"}


def message_div(text=""):
    """A line of text for the messages of a page (e.g. "No R1 data in this event.")"""
    return Div(text=text, styles={"font-size": "11pt", "color": "#666", "padding": "4px 0"}, width=900, height=28)


def _first_value(rows, names):
    """First value of one of the columns ``names`` in the rows ``{kind: row}``"""
    for name in names:
        for values in rows.values():
            if name in values:
                return values[name]
    return None


def event_type_name(value):
    """Name of a ctapipe event type (e.g. ``SUBARRAY``), the value itself if unknown"""
    try:
        return EventType(int(value)).name
    except (ValueError, TypeError):
        return str(value)


def format_time(value):
    """ISO UTC time of an astropy Time or of unix seconds"""
    try:
        if isinstance(value, Time):
            return value.utc.isot
        return Time(float(value), format="unix", scale="utc").isot
    except (ValueError, TypeError):
        return str(value)


def event_description(key, rows):
    """Description of an event: its ids, type and time (from its rows of any kind)"""
    if key is None:
        return ""
    obs_id, event_id = key
    text = f"obs_id {obs_id} · event_id {event_id}"
    event_type = _first_value(rows, ("event_type",))
    if event_type is not None:
        text += f" · {event_type_name(event_type)}"
    time = _first_value(rows, ("time", "event_time"))
    if time is not None:
        text += f" · {format_time(time)}"
    return text


class Page:
    """
    A page of the viewer. ``layout`` is its bokeh layout, ``refresh()`` updates it from the
    store (called when the page is opened, and when the data or the state of the user change).
    """

    title = ""
    #: minimum time between two refreshes for new data (s)
    min_interval = 0.0

    def __init__(self, session):
        self.session = session
        self.store = session.store

    def refresh(self):
        """Update the page from the store and the state of the user"""
        raise NotImplementedError


class LevelRates:
    """Rates of the data of a level received from the selected telescopes, in time (one line per telescope)"""

    def __init__(self, session, kind, width=1000, height=200):
        self.session, self.kind = session, kind
        series = {tel_id: (f"TEL {tel_id}", session.color(tel_id)) for tel_id in session.all_tel_ids}
        self.panel = RatePanel(f"Rate of the {LEVEL_NAMES.get(kind, kind)} data received", series, width=width,
                               height=height)
        self.layout = self.panel.layout

    def refresh(self):
        """Show the rates of the selected telescopes"""
        tel_ids = self.session.tel_ids
        store = self.session.store
        self.panel.update({tel_id: store.rate_history(tel_id, self.kind) for tel_id in tel_ids}, visible=tel_ids)


def telescope_header(session, tel_id):
    """Header of the block of a telescope in a page: its name in its color, its own Prev / Next"""
    title = Div(text=f"<h3 style='margin: 4px 0 0 0; color: {session.color(tel_id)}'>TEL {tel_id}</h3>", width=70)
    prev_button = Button(label="◀", width=36, height=28)
    next_button = Button(label="▶", width=36, height=28)
    prev_button.on_click(lambda: session.step(-1, [tel_id]))
    next_button.on_click(lambda: session.step(+1, [tel_id]))
    return row(title, prev_button, next_button)
