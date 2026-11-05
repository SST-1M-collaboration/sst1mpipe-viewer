"""Table of the scalar values of a row (e.g. the DL1 parameters of an event)"""

import numpy as np
from bokeh.models import ColumnDataSource, DataTable, NumberFormatter, TableColumn

from ..units import column_unit

__all__ = ["ParameterTable", "scalar_items"]


def scalar_items(row, exclude=()):
    """(name, value) of the scalar numeric values of a row"""
    items = []
    for name, value in row.items():
        if name in exclude or np.ndim(value) != 0:
            continue
        try:
            items.append((name, float(value)))
        except (TypeError, ValueError):
            continue
    return items


class ParameterTable:
    """Table name / value / unit"""

    def __init__(self, width=380, height=560):
        self.source = ColumnDataSource(data=dict(name=[], value=[], unit=[]))
        self.table = DataTable(
            source=self.source,
            columns=[
                TableColumn(field="name", title="Parameter", width=210),
                TableColumn(field="value", title="Value", width=100, formatter=NumberFormatter(format="0.[0000]")),
                TableColumn(field="unit", title="Unit", width=60),
            ],
            width=width, height=height, index_position=None, sortable=True,
        )
        self.layout = self.table

    def set_items(self, items):
        """Show (name, value) items"""
        self.source.data = dict(
            name=[name for name, _ in items],
            # numbers (not strings) so that the column sorts numerically, NaN shown empty
            value=[value for _, value in items],
            unit=[column_unit(name) for name, _ in items],
        )
