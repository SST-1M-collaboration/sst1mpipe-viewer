"""Tables of the fields of an event (values of the scalars, shape and type of the arrays)"""

import numpy as np
from astropy.time import Time
from bokeh.models import ColumnDataSource, DataTable, NumberFormatter, StringFormatter, TableColumn
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
            details = Time(number, format="unix", scale="utc").isot
        items.append((prefix + name, number, details))
    return items


class FieldsTable:
    """Table field / value / details / unit of all the fields of an event"""

    def __init__(self, width=440, height=560):
        self.source = ColumnDataSource(data=dict(name=[], value=[], details=[], unit=[]))
        self.table = DataTable(
            source=self.source,
            columns=[
                TableColumn(field="name", title="Field", width=150),
                TableColumn(field="value", title="Value", width=110, formatter=NumberFormatter(format="0.[0000]")),
                TableColumn(field="details", title="Details", width=230, formatter=StringFormatter()),
                TableColumn(field="unit", title="Unit", width=50),
            ],
            width=width, height=height, index_position=None, sortable=True,
        )
        self.layout = self.table

    def set_rows(self, rows):
        """Show the fields of rows ``{label: row}`` (the fields of all but the first are prefixed by the label)"""
        items = []
        for i, (label, row) in enumerate(rows.items()):
            items += field_items(row, prefix="" if i == 0 else f"{label}.")
        data = dict(
            name=[name for name, _, _ in items],
            value=[number for _, number, _ in items],
            details=[details for _, _, details in items],
            unit=[column_unit(name.split(".")[-1]) for name, _, _ in items],
        )
        if data != self.source.data:
            self.source.data = data
