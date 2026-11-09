"""Tables of the fields of an event (values of the scalars, shape and type of the arrays)"""

import numpy as np
from astropy.time import Time
from bokeh.models import ColumnDataSource, DataTable, StringFormatter, TableColumn
from ctapipe.containers import EventType

from ..units import column_unit

__all__ = ["FieldsTable", "field_items"]

#: fields whose values are event types
EVENT_TYPE_FIELDS = ("event_type", "_event_type")
#: fields whose values are times (unix seconds when read from a table)
TIME_FIELDS = ("time", "event_time")


def _summary(value):
    """Number (or NaN) and readable description of a field value"""
    if isinstance(value, np.ndarray) and value.dtype == object and value.ndim == 0:
        value = value[()]
    if isinstance(value, Time):
        return np.nan, value.utc.isot
    array = np.asarray(value)
    if array.ndim == 0:
        try:
            number = float(array)
        except (TypeError, ValueError):
            return np.nan, str(value)
        return number, ""
    # arrays are shown in the cameras and plots: only described here (no computation)
    return np.nan, f"array {array.shape} {array.dtype}"


def field_items(row, prefix=""):
    """(name, number or NaN, details) of every field of a row: scalars, arrays (summary), times"""
    items = []
    for name, value in row.items():
        number, details = _summary(value)
        if name in EVENT_TYPE_FIELDS and np.isfinite(number):
            try:
                details = EventType(int(number)).name
            except ValueError:
                pass
        elif name in TIME_FIELDS and np.isfinite(number):
            # a time: shown as an ISO date only
            number, details = np.nan, Time(number, format="unix", scale="utc").isot
        items.append((prefix + name, number, details))
    return items


def _text(number, details):
    """Readable value of a field: the number, and its description (e.g. the name of an event type)"""
    if np.isfinite(number):
        text = f"{number:.6g}" if number != int(number) or abs(number) >= 1e15 else str(int(number))
        return f"{text} ({details})" if details else text
    return details or "–"


class FieldsTable:
    """
    Table of all the fields of the displayed events of the telescopes: one row per field, one
    column per telescope (value of the scalars, description of the arrays, times, event types)
    """

    def __init__(self, width=900, height=400):
        self.source = ColumnDataSource(data=dict(name=[], unit=[]))
        self.table = DataTable(source=self.source, columns=[], width=width, height=height, index_position=None,
                               sortable=False)
        self._tel_ids = None
        self.layout = self.table

    def set_rows(self, rows):
        """
        Show the fields of the rows of the telescopes ``{tel_id: {label: row}}`` (the fields of all
        the rows but the first of a telescope are prefixed by their label, e.g. ``trigger.time``)
        """
        tel_ids = list(rows)
        if tel_ids != self._tel_ids:
            # new columns only when the telescopes change
            self._tel_ids = tel_ids
            self.table.columns = (
                [TableColumn(field="name", title="Field", width=200)]
                + [TableColumn(field=f"tel_{t}", title=f"TEL {t}", width=260, formatter=StringFormatter())
                   for t in tel_ids]
                + [TableColumn(field="unit", title="Unit", width=60)]
            )
        values = {}
        names = []
        for tel_id, tel_rows in rows.items():
            for i, (label, row) in enumerate(tel_rows.items()):
                for name, number, details in field_items(row, prefix="" if i == 0 else f"{label}."):
                    if name not in values:
                        values[name] = {}
                        names.append(name)
                    values[name][tel_id] = _text(number, details)
        data = dict(name=names, unit=[column_unit(name.split(".")[-1]) for name in names])
        for tel_id in tel_ids:
            data[f"tel_{tel_id}"] = [values[name].get(tel_id, "") for name in names]
        if data != self.source.data:
            self.source.data = data
