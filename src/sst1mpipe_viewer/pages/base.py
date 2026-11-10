"""Base class of the pages of the viewer, and helpers shared by the pages"""

from astropy.time import Time
from bokeh.layouts import row
from bokeh.models import Button, Div
from ctapipe.containers import EventType

from ..components import RatePanel

__all__ = ["Page", "LevelRates", "message_div", "event_description", "telescope_header", "set_stale",
           "stale_message"]

#: names of the data levels in the titles
LEVEL_NAMES = {"r0": "R0", "r1": "R1", "dl0": "DL0", "dl1": "DL1", "dl2": "DL2", "dl2_stereo": "DL2 stereo",
               "trigger": "trigger"}


#: style of the displays which do not show the current event: blurred and faded
STALE_STYLES = {"filter": "blur(1.5px)", "opacity": "0.7"}


def set_stale(layout, stale):
    """
    Blur a layout whose displays are not those of the current event (``stale``), or show it
    normally: the user sees at once that the displays are those of another event.
    """
    styles = STALE_STYLES if stale else {}
    if dict(layout.styles) != styles:
        layout.styles = styles


def stale_message(session, tel_id, kind, key, has_data):
    """
    Explain why the displays of a telescope do not show its current event (its level ``kind`` is
    missing or not valid, see `sst1mpipe_viewer.validity`).

    Parameters
    ----------
    session : ViewerSession
    tel_id : int
    kind : str
        The data level of the page.
    key : tuple or None
        The event whose data would be displayed.
    has_data : bool
        Whether this event has data of the level.

    Returns
    -------
    str or None
        None if the displays show the current event, else the message for the user.
    """
    current = session.current_key(tel_id)
    level = LEVEL_NAMES.get(kind, kind)
    if has_data and key == current:
        return None
    if current is None:
        return f"No {level} data."
    if has_data:
        return f"Event {current[1]} has no valid {level} data: event {key[1]} is shown."
    return f"No {level} data in event {current[1]}."


def message_div(text="", width=900, height=28):
    """A line of text for the messages of a page (e.g. "No R1 data in this event.")"""
    styles = {"font-size": "11pt", "color": "#c62828", "padding": "4px 0"}
    return Div(text=text, styles=styles, width=width, height=height)


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
    """
    Rates of the data of a level received from the selected telescopes, per minute (one line per
    telescope, with error bars), and a dashed vertical line at the time of the displayed event of
    each telescope
    """

    def __init__(self, session, kind, width=1000, height=200):
        self.session, self.kind = session, kind
        series = {tel_id: (f"TEL {tel_id}", session.color(tel_id)) for tel_id in session.all_tel_ids}
        markers = {tel_id: session.color(tel_id) for tel_id in session.all_tel_ids}
        self.panel = RatePanel(f"Rate of the {LEVEL_NAMES.get(kind, kind)} data per minute"
                               " (dashed lines: displayed events)", series, markers=markers, width=width,
                               height=height)
        self.layout = self.panel.layout

    def refresh(self):
        """Show the rates of the selected telescopes and the times of their displayed events"""
        session, store = self.session, self.session.store
        tel_ids = session.tel_ids
        self.panel.update({tel_id: store.rate_history(tel_id, self.kind) for tel_id in tel_ids}, visible=tel_ids)
        self.panel.set_markers({tel_id: store.event_time(tel_id, session.event_key(tel_id, self.kind))
                                for tel_id in tel_ids})


def telescope_header(session, tel_id):
    """Header of the block of a telescope in a page: its name in its color, its own Prev / Next"""
    title = Div(text=f"<h3 style='margin: 4px 0 0 0; color: {session.color(tel_id)}'>"
                     f"{session.tel_label(tel_id)}</h3>", width=85)
    prev_button = Button(label="◀", width=36, height=28)
    next_button = Button(label="▶", width=36, height=28)
    prev_button.on_click(lambda: session.step(-1, [tel_id]))
    next_button.on_click(lambda: session.step(+1, [tel_id]))
    return row(title, prev_button, next_button)
