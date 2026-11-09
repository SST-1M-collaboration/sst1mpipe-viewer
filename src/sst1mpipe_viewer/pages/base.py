"""Base class of the pages (tabs) of the viewer"""

from astropy.time import Time
from bokeh.models import Div
from ctapipe.containers import EventType

__all__ = ["Page", "message_div", "event_description"]


def message_div(text=""):
    return Div(text=text, styles={"font-size": "11pt", "color": "#666", "padding": "4px 0"}, width=900, height=28)





def _first_value(rows, names):
    """First value of one of the columns ``names`` in the rows ``{kind: row}``"""
    for name in names:
        for row in rows.values():
            if name in row:
                return row[name]
    return None


def event_type_name(value):
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
    store (called when the page is shown and when the store or the session state change).
    """

    title = ""
    #: minimum time between two refreshes for new data (s)
    min_interval = 0.0

    def __init__(self, session):
        self.session = session
        self.store = session.store

    def refresh(self):
        raise NotImplementedError


def telescope_header(session, tel_id):
    """Header of the block of a telescope in a page: its name in its color, its own Prev / Next"""
    from bokeh.layouts import row
    from bokeh.models import Button, Div

    title = Div(text=f"<h3 style='margin: 4px 0 0 0; color: {session.color(tel_id)}'>TEL {tel_id}</h3>", width=70)
    prev_button = Button(label="◀", width=36, height=28)
    next_button = Button(label="▶", width=36, height=28)
    prev_button.on_click(lambda: session.step(-1, [tel_id]))
    next_button.on_click(lambda: session.step(+1, [tel_id]))
    return row(title, prev_button, next_button)
