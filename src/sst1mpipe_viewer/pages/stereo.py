"""
DL2 Stereo page: the showers reconstructed with several telescopes (``event.dl2.stereo`` of
ctapipe, kind ``"dl2_stereo"`` of the store).

The stereo data belong to the subarray, not to a telescope: the page shows the displayed stereo
event (its reconstructed core on the ground with the telescopes, all its fields in a table) and
the accumulated statistics of all the stereo events. The algorithm of each group of quantities
(geometry, energy, classification) is chosen in a menu.
"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import ColumnDataSource, Div, LabelSet, Range1d
from bokeh.plotting import figure

from ..components import FieldsTable, RatePanel
from ..components.histogram import add_caption, format_number
from ..dl2 import SUBARRAY_ID, find_algorithms, generic_columns
from ..validity import row_is_valid
from .base import Page, event_description, message_div, missing_message, set_event_label, telescope_header
from .statistics import StatisticsPage

__all__ = ["DL2StereoPage"]

KIND = "dl2_stereo"
#: color of the reconstructed core and of the ring of the telescopes used in the reconstruction
CORE_COLOR = "#e53935"
#: default half size (m) of the view of the ground (``display: ground_radius`` of the configuration)
GROUND_RADIUS = 500.0


class DL2StereoPage(Page):
    """The displayed stereo DL2 event and the statistics of all the stereo events"""

    title = "DL2 Stereo"

    def __init__(self, session):
        super().__init__(session)
        color = session.color(SUBARRAY_ID)
        self.rates = RatePanel("Rate of the stereo DL2 data per minute (dashed line: displayed event)",
                               {SUBARRAY_ID: ("Subarray", color)}, markers={SUBARRAY_ID: color}, width=1000,
                               height=200)
        self.header, self.event_label = telescope_header(session, SUBARRAY_ID)
        self.message = message_div(width=600)

        # the telescopes on the ground and the reconstructed core of the displayed event
        # a fixed view (no pan nor wheel zoom), centred between the telescopes
        display = self.store.statistics_configs[KIND].get("display") or {}
        self.ground_radius = float(display.get("ground_radius", GROUND_RADIUS))
        self.ground = figure(title="Reconstructed core on the ground", width=460, height=430, match_aspect=True,
                             tools="box_zoom,reset,save", toolbar_location="above",
                             x_range=Range1d(-self.ground_radius, self.ground_radius),
                             y_range=Range1d(-self.ground_radius, self.ground_radius))
        self.ground.toolbar.active_drag = None
        self.ground.xaxis.axis_label = "x (m), ground frame"
        self.ground.yaxis.axis_label = "y (m), ground frame"
        self.telescopes_source = ColumnDataSource(data=dict(x=[], y=[], label=[], color=[], line=[]))
        self.ground.scatter(x="x", y="y", source=self.telescopes_source, size=16, fill_color="color",
                            line_color="line", line_width=3)
        self.ground.add_layout(LabelSet(x="x", y="y", text="label", source=self.telescopes_source, y_offset=12,
                                        text_align="center", text_font_size="10pt", text_font_style="bold"))
        self.core_source = ColumnDataSource(data=dict(x=[], y=[]))
        self.ground.scatter(x="x", y="y", source=self.core_source, marker="x", size=18, line_color=CORE_COLOR,
                            line_width=3)
        self.caption = add_caption(self.ground)
        self.summary = add_caption(self.ground)
        self._subarray = None

        self.fields = FieldsTable(width=620, height=430, labels={SUBARRAY_ID: "Subarray"})
        # the statistics of all the stereo events, with the menus of the algorithms
        self.statistics = StatisticsPage(session, KIND)
        self._shown = False  # a stereo event is displayed
        self.layout = column(
            self.rates.layout,
            row(self.header, self.message),
            row(self.ground, self.fields.layout),
            Div(text="<h3 style='margin: 10px 0 0 0'>Statistics of the stereo events</h3>"),
            self.statistics.layout,
        )

    def _show_message(self, text):
        """Show a message next to the header (only sent to the browser if it changed)"""
        if self.message.text != text:
            self.message.text = text

    def _telescopes(self, used):
        """Draw the telescopes of the subarray, those ``used`` in the reconstruction ringed in red"""
        subarray = self.store.subarray
        if subarray is None:
            return
        tel_ids = [int(t) for t in subarray.tel_ids]
        positions = np.array([subarray.positions[t].to_value("m") for t in tel_ids])
        data = dict(x=positions[:, 0], y=positions[:, 1], label=[f"TEL {t}" for t in tel_ids],
                    color=[self.session.color(t) for t in tel_ids],
                    line=[CORE_COLOR if t in used else "white" for t in tel_ids])
        if subarray is not self._subarray:
            # the view is fixed: ``ground_radius`` around the centre of the telescopes
            centre = positions[:, :2].mean(axis=0)
            for axis_range, value in ((self.ground.x_range, centre[0]), (self.ground.y_range, centre[1])):
                start, end = float(value - self.ground_radius), float(value + self.ground_radius)
                axis_range.update(start=start, end=end, reset_start=start, reset_end=end)
        if subarray is not self._subarray or data["line"] != list(self.telescopes_source.data["line"]):
            self._subarray = subarray
            self.telescopes_source.data = data

    def _used_telescopes(self, telescopes):
        """Ids of the telescopes of the ``telescopes`` field: a list of ids, or a mask of the subarray telescopes"""
        if telescopes is None:
            return []
        telescopes = np.atleast_1d(np.asarray(telescopes))
        subarray = self.store.subarray
        if telescopes.dtype == bool and subarray is not None and len(telescopes) == len(subarray.tel_ids):
            return [int(t) for t, used in zip(subarray.tel_ids, telescopes) if used]
        if telescopes.dtype == bool:
            return []
        return [int(t) for t in telescopes]

    def refresh(self):
        """Show the displayed stereo event, the rate and the statistics"""
        session, store = self.session, self.store
        self.statistics.refresh()
        key = session.event_key(SUBARRAY_ID, KIND)
        self.rates.update({SUBARRAY_ID: store.rate_history(SUBARRAY_ID, KIND)})
        self.rates.set_markers({SUBARRAY_ID: store.event_time(SUBARRAY_ID, key)})
        rows = store.event(SUBARRAY_ID, key, (KIND, "trigger")) if key is not None else {}
        data = rows.get(KIND)
        displayed = data is not None and row_is_valid(KIND, data)
        if not displayed and session.follow and self._shown:
            # Live: the event displayed stays until another one can be displayed
            return
        set_event_label(self.event_label, key if displayed or not session.follow else None)
        if data is None or not row_is_valid(KIND, data):
            # a level which is not valid is not displayed
            self._shown = False
            self._show_message(missing_message(session, SUBARRAY_ID, KIND))
            self._telescopes([])
            self.core_source.data = dict(x=[], y=[])
            self.caption.text = self.summary.text = ""
            self.fields.set_rows({})
            return
        self._shown = True
        self._show_message("")
        # the fields of the algorithms chosen in the menus, with their generic names
        algorithms = find_algorithms(data, stereo=True)
        chosen = self.statistics.algorithms()
        combination = {group: chosen.get(group) if chosen.get(group) in names else next(iter(names))
                       for group, names in algorithms.items()}
        values = generic_columns(data, algorithms, combination)

        def number(name):
            try:
                return float(values[name])
            except (KeyError, TypeError, ValueError):
                return np.nan

        core = (number("core_x"), number("core_y"))
        self.core_source.data = dict(x=[core[0]], y=[core[1]]) if all(np.isfinite(core)) else dict(x=[], y=[])
        used = self._used_telescopes(values.get("geometry_telescopes"))
        self._telescopes(used)
        self.caption.text = event_description(key, rows)
        self.summary.text = (
            f"core ({format_number(core[0])}, {format_number(core[1])}) m · alt {format_number(number('alt'))}°"
            f" · az {format_number(number('az'))}° · energy {format_number(number('energy'))} TeV"
            f" · gammaness {format_number(number('prediction'))}"
            + (f" · telescopes {', '.join(str(t) for t in used)}" if used else "")
        )
        self.fields.set_rows({SUBARRAY_ID: {KIND: data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})}})
