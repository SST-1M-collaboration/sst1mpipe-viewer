"""
Conversion of the inputs of the viewer (ctapipe containers, table rows, tables) to columns.

The viewer understands a single format: a dict ``{column name: numpy array}`` whose arrays
share their first dimension (the rows). The column names are those of the ctapipe HDF5
tables written by the ``DataWriter``: the fields of the container keep their name and the
fields of its sub-containers take the prefix of the sub-container, e.g. a
``DL1CameraContainer`` gives ``image``, ``peak_time``, ``image_mask``, ``hillas_intensity``,
``leakage_intensity_width_2``, ... as the columns of ``/dl1/event/telescope/images`` and
``/dl1/event/telescope/parameters``.

Quantities are converted to the canonical units of `CANONICAL_UNITS` (the units of the
ctapipe tables) when they are compatible, the time columns of tables to unix seconds (a single
time, e.g. of a container, is kept as an astropy ``Time``: its conversion is slow).
"""

from collections.abc import Mapping
from enum import Enum

import astropy.units as u
import numpy as np
from astropy.table import Row, Table
from astropy.time import Time
from ctapipe.core import Container

__all__ = ["CANONICAL_UNITS", "KEY_COLUMNS", "container_to_dict", "to_columns", "n_rows", "iter_rows"]

#: columns identifying an event of a telescope
KEY_COLUMNS = ("obs_id", "event_id", "tel_id")

#: unit of the values of the viewer for the quantities of these physical types
CANONICAL_UNITS = {
    "angle": u.deg,
    "length": u.m,
    "time": u.ns,
    "energy": u.TeV,
}


#: types converted directly by numpy (the most frequent values: fast path)
_PLAIN_TYPES = (float, int, bool, np.floating, np.integer, np.bool_)
#: unit -> canonical unit (or None), cached: looking up the physical type of a unit is slow
_UNIT_CACHE = {}


def _canonical_unit(unit):
    """Unit of the viewer for the values of a unit (same physical type), None if none"""
    try:
        return _UNIT_CACHE[unit]
    except KeyError:
        result = _UNIT_CACHE[unit] = CANONICAL_UNITS.get(str(unit.physical_type))
        return result


def _to_value(value):
    """Plain value (numpy array or scalar) of a quantity, time or value"""
    if isinstance(value, _PLAIN_TYPES) or type(value) is np.ndarray:
        return np.asarray(value)
    if isinstance(value, u.Quantity):
        unit = _canonical_unit(value.unit)
        return np.asarray(value.to_value(unit) if unit is not None and unit != value.unit else value.value)
    if isinstance(value, Time):
        if value.isscalar:
            # converting a time is slow (scale conversion): a single time is kept as it is (a 0-d
            # object array) and converted only to be shown
            wrapped = np.empty((), dtype=object)
            wrapped[()] = value
            return wrapped
        return np.asanyarray(value.unix)
    if isinstance(value, Enum):  # e.g. EventType
        return np.asanyarray(value.value)
    return np.asanyarray(value)


def container_to_dict(container):
    """
    Flat dict of a container as written by the ctapipe ``DataWriter``: its fields keep their
    names, the fields of its sub-containers are prefixed by the prefix of the sub-container.
    Map fields (e.g. ``tel``) are ignored.
    """
    result = {}
    for key, value in container.items():
        if isinstance(value, Container):
            result.update(value.as_dict(recursive=True, flatten=True, add_prefix=True))
        elif isinstance(value, Mapping):
            continue
        else:
            result[key] = value
    return result


def to_columns(data, **extra):
    """
    Columns ``{name: array with the rows as first dimension}`` of ``data``: a ctapipe
    `~ctapipe.core.Container`, a mapping ``{name: value}`` or an astropy `~astropy.table.Row`
    are one row, an astropy `~astropy.table.Table` gives all its rows (wrap a mapping of
    columns in a ``Table`` to push several rows).

    The ``extra`` values (e.g. ``tel_id=1``) are added to every row. ``None`` values are dropped.
    """
    if isinstance(data, Table):
        columns = {name: _to_value(data[name]) for name in data.colnames}
        n = len(data)
    else:
        if isinstance(data, Container):
            row = container_to_dict(data)
        elif isinstance(data, Row):
            row = {name: data[name] for name in data.colnames}
        elif isinstance(data, Mapping):
            row = dict(data)
        else:
            raise TypeError(f"Cannot convert {type(data).__name__} to columns")
        columns = {}
        for name, value in row.items():
            if value is None:
                continue
            columns[name] = _to_value(value)[np.newaxis, ...]
        n = 1

    for name, value in extra.items():
        if value is not None:
            columns[name] = np.full(n, value)

    return columns


def n_rows(columns):
    """Number of rows of columns (0 without columns)"""
    for value in columns.values():
        return len(value)
    return 0


def iter_rows(columns):
    """Rows ``{name: value}`` of columns"""
    for i in range(n_rows(columns)):
        yield {name: value[i] for name, value in columns.items()}
