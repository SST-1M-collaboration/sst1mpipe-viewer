"""
Shared state of the viewer: the events received and the accumulated statistics.

Any thread can push data to the store; the bokeh sessions only read it. One store is shared by
all the sessions of a server, so that all the browsers show the same events and statistics (and a
reset resets them for everyone).

Two ways of giving data
-----------------------
- **Event by event** (``push_event``, ``push_container``, ``push_row``), e.g. a live stream:
  the last ``max_events`` events of each telescope are kept for the display, the DL1 and DL2
  rows fill the statistics. Pushing is cheap (rates of several kHz): the statistics are filled in
  vectorized batches (when they are read, or every ``flush_size`` rows) and the parameters of
  sst1mpipe in the camera frame are converted when needed (`sst1mpipe_viewer.frames`).
- **Tables** (``push_table``), e.g. a file: all the rows are processed at once (vectorized) and
  every event of the tables can be displayed (``event_keys``, ``event``), not only the last ones.

Kinds of data
-------------
``r0``, ``r1``, ``dl0``, ``dl1``, ``dl2`` and ``trigger``: the rows are those of the ctapipe
tables (``/r1/event/telescope/tel_XXX``, ``/dl1/event/telescope/images/tel_XXX`` and
``/dl1/event/telescope/parameters/tel_XXX``, ``/dl2/event/telescope/parameters/tel_XXX`` of
sst1mpipe, ``/dl1/event/telescope/trigger``, ...) or the flattened containers of these levels
(`sst1mpipe_viewer.normalize.container_to_dict`).
Every row needs ``obs_id``, ``event_id`` and ``tel_id`` (given in the row or as keywords).
The rows of the same event (``obs_id``, ``event_id``) of a telescope are merged, e.g. a DL1
image row and a DL1 parameter row, or a R1 row and its trigger row.

Rates
-----
The rate of each telescope and data level (`rate_history`) is the number of events whose level is
*valid* (`sst1mpipe_viewer.validity`) per second, computed from the timestamps of the events (the
``time`` of their trigger row or the ``event_time`` of their R0 / R1 / DL0 row), per minute with
its statistical uncertainty (`sst1mpipe_viewer.rates`). The events without timestamp are not in
the rates.
"""

import threading
import time
from collections import Counter, OrderedDict, deque

import astropy.units as u
import numpy as np
from astropy.time import Time
from ctapipe.coordinates import GroundFrame
from ctapipe.instrument import SubarrayDescription

from .config import STATISTICS_KINDS, build_statistics, load_statistics_config
from .dl2 import (
    SUBARRAY_ID,
    add_sst1mpipe_algorithm,
    combination_key,
    combinations,
    container_row,
    find_algorithms,
    generic_columns,
)
from .dl3 import DL3Data
from .frames import CAMERA_FRAME_PREFIX, add_telescope_frame_parameters
from .normalize import KEY_COLUMNS, n_rows, to_columns, to_row
from .rates import RATE_BIN, binned_rates, live_rates
from .validity import container_is_valid, row_is_valid, valid_rows

__all__ = ["KINDS", "ViewerStore"]

#: kinds of data accepted by the store
KINDS = ("r0", "r1", "dl0", "dl1", "dl2", "dl2_stereo", "trigger")
#: kinds of data of a telescope (the stereo DL2 are those of the subarray)
TELESCOPE_KINDS = tuple(kind for kind in KINDS if kind != "dl2_stereo")
#: DL2 kinds: their statistics are accumulated per combination of algorithms (`sst1mpipe_viewer.dl2`)
DL2_KINDS = ("dl2", "dl2_stereo")

#: time window (s) of the rates of received rows
RATE_WINDOW = 10.0
#: number of bins (minutes) of the rate histories of the live data: 24 hours
RATE_HISTORY_BINS = 1440
#: an event pushed again with a timestamp differing by more than this (s) is the event of a new pass of a
#: replay in loop (the times of the levels of an event, e.g. trigger and R0, can differ slightly)
REPLAY_TIME_SHIFT = 0.5
#: number of the last events pushed of each telescope whose timestamp and counted levels are remembered
RATE_EVENTS = 5000
#: number of rows converted to the telescope frame kept for the display
CONVERTED_CACHE_SIZE = 64
#: columns with the time of the events (unix seconds in the tables)
TIME_COLUMNS = ("time", "event_time")


#: kinds whose containers pushed event by event are converted only when displayed
LAZY_KINDS = ("r0", "r1", "dl0")


class _LazyRow:
    """Container pushed event by event, converted to a row when its event is displayed"""

    __slots__ = ("container", "keys", "_row")

    def __init__(self, container, keys):
        self.container = container
        self.keys = keys
        self._row = None

    def row(self):
        """The row of the container (converted at the first call, the container is then dropped)"""
        if self._row is None:
            columns = to_columns(self.container, **self.keys)
            self._row = _row(columns, 0)
            self.container = None
        return self._row


def _as_row(value):
    """Row of a stored value (a row, or a `_LazyRow` converted now)"""
    return value.row() if isinstance(value, _LazyRow) else value


def _row(columns, i):
    """Row ``i`` of columns"""
    return {name: values[i] for name, values in columns.items()}


def _select(columns, mask):
    """Rows of columns selected by a boolean mask"""
    return {name: values[mask] for name, values in columns.items()}


class _Tables:
    """
    Events of a telescope given as tables: the columns of each kind and the row of each event,
    the events in the order of their first row.
    """

    def __init__(self):
        self.keys = []
        self.positions = {}  # key -> position in keys
        self.kinds = {}  # kind -> list of (columns, {key: row}, valid rows)
        self.times = {}  # key -> time of the event (unix s), from the tables with a time column
        self.version = 0  # incremented at each table added

    def add(self, kind, columns, valid):
        """Add a table of a data level (its columns, and which of its rows are valid)"""
        keys = list(zip(np.asarray(columns["obs_id"]).astype(int).tolist(),
                        np.asarray(columns["event_id"]).astype(int).tolist()))
        rows = {}
        for i, key in enumerate(keys):
            rows[key] = i
            if key not in self.positions:
                self.positions[key] = len(self.keys)
                self.keys.append(key)
        self.kinds.setdefault(kind, []).append((columns, rows, valid))
        time_column = next((name for name in TIME_COLUMNS if name in columns), None)
        if time_column is not None and np.issubdtype(np.asarray(columns[time_column]).dtype, np.number):
            self.times.update(zip(keys, np.asarray(columns[time_column], dtype=float).tolist()))
        self.version += 1

    def event_times(self, kind):
        """Times (unix s) of the events whose data level is valid (NaN for the events without time)"""
        times = []
        for _, rows, valid in self.kinds.get(kind, ()):
            times += [self.times.get(key, np.nan) for key, is_valid in zip(rows, valid) if is_valid]
        return np.asarray(times, dtype=float)

    def last_valid_key(self, kind):
        """Key of the last event whose data level is valid, None if none"""
        best = None
        for columns, _, valid in self.kinds.get(kind, ()):
            indices = np.flatnonzero(valid)
            if len(indices) == 0:
                continue
            key = (int(columns["obs_id"][indices[-1]]), int(columns["event_id"][indices[-1]]))
            if best is None or self.positions[key] > self.positions[best]:
                best = key
        return best

    def event(self, key, kinds=None):
        """Rows ``{kind: row}`` of an event (of the data levels ``kinds``, all if None)"""
        result = {}
        for kind, tables in self.kinds.items():
            if kinds is not None and kind not in kinds:
                continue
            for columns, rows, _ in tables:
                if key in rows:
                    result[kind] = {**result.get(kind, {}), **_row(columns, rows[key])}
        return result


class ViewerStore:
    """
    Events and accumulated statistics of the telescopes.

    Parameters
    ----------
    subarray : ctapipe.instrument.SubarrayDescription or None
        Subarray of the data (camera geometries, telescope positions). It can be set later
        with `set_subarray`.
    statistics_configs : dict or None
        Configuration of the statistics of each data level ``{"dl1": config, "dl2": config}``
        (`sst1mpipe_viewer.config.load_statistics_config`), the default one for a missing level.
    max_events : int
        Number of events pushed event by event kept per telescope (for the display).
    flush_size : int
        Number of DL1 / DL2 rows pushed event by event after which the statistics are filled.
    """

    def __init__(self, subarray=None, statistics_configs=None, max_events=200, flush_size=2000):
        self._lock = threading.RLock()
        self.subarray = subarray
        configs = dict(statistics_configs or {})
        self.statistics_configs = {kind: configs.get(kind) or load_statistics_config(kind=kind)
                                   for kind in STATISTICS_KINDS}
        self.max_events = int(max_events)
        self.flush_size = int(flush_size)
        self.source_description = ""
        self.version = 0  # incremented at each change
        #: the DL3 events (not per telescope): ``store.dl3.push(events, header)``
        self.dl3 = DL3Data(configs.get("dl3"), on_change=self._changed)
        self._clear()

    def _changed(self):
        """Mark a change of the data: the pages are refreshed"""
        with self._lock:
            self.version += 1

    def _clear(self):
        """Empty state: no event, no statistics"""
        self._events = {}  # tel_id -> OrderedDict[(obs_id, event_id) -> {kind: row}], pushed event by event
        self._tables = {}  # tel_id -> _Tables, pushed as tables
        self._latest = {}  # (tel_id, kind) -> (obs_id, event_id)
        self._counts = Counter()  # (tel_id, kind) -> number of rows received
        self._arrivals = {}  # (tel_id, kind) -> deque of [time, n rows] of the last RATE_WINDOW s
        self._latest_valid = {}  # (tel_id, kind) -> (obs_id, event_id) of the last event with a valid level
        self._history = {}  # (tel_id, kind) -> {minute (event time // RATE_BIN): n valid events}
        self._history_start = {}  # (tel_id, kind) -> time of the first valid event (unix s)
        self._last_time = {}  # tel_id -> time of the last event pushed (unix s)
        # tel_id -> OrderedDict[(obs_id, event_id) -> [time or None, levels counted, levels waiting for the time]]
        self._rate_events = {}
        self._table_history = {}  # (tel_id, kind) -> (tables version, (times, rates, errors)), cache
        # (kind, tel_id, combination of DL2 algorithms or None) -> StatisticsSet
        self._statistics = {}
        self._algorithms = {}  # (kind, tel_id) -> {group: [algorithm, ...]}, the DL2 algorithms seen
        self._pending = {}  # (kind, tel_id) -> list of columns not yet in the statistics
        self._n_pending = 0
        self._needed_columns = {}  # kind -> columns used by the statistics
        self._converted = {}  # (tel_id, key, kind, n columns) -> row converted to the telescope frame

    # ------------------------------------------------------------------ input
    def set_subarray(self, subarray):
        """Set the subarray (camera geometries and positions of the telescopes)"""
        with self._lock:
            self.subarray = subarray
            self.version += 1

    def add_telescopes(self, subarray):
        """
        Add the telescopes of ``subarray`` not yet in the subarray of the store (e.g. the files
        of sst1mpipe have one telescope each), or set it if the store has none. The positions of
        the added telescopes are taken relative to the reference location of the store's subarray.
        """
        with self._lock:
            current = self.subarray
            if current is None:
                self.set_subarray(subarray)
                return
            new = [tel_id for tel_id in subarray.tel_ids if tel_id not in current.tel]
            if not new:
                return
            earth = subarray.tel_earth_locations
            positions = {}
            for t in new:
                ground = GroundFrame.from_earth_location(earth[t], current.reference_location)
                positions[t] = u.Quantity([ground.x, ground.y, ground.z]).to(u.m)
            merged = SubarrayDescription(
                name=current.name,
                tel_positions={**current.positions, **positions},
                tel_descriptions={**current.tel, **{t: subarray.tel[t] for t in new}},
                reference_location=current.reference_location,
            )
            self.set_subarray(merged)

    def push_container(self, kind, container, *, obs_id=None, event_id=None, tel_id=None):
        """
        Push a container of a telescope event (e.g. a ``DL1CameraContainer``). The R0, R1 and DL0
        containers are converted only if their event is displayed: they must not be modified
        after being pushed (the ctapipe event sources create new containers for each event).
        """
        if kind in LAZY_KINDS and obs_id is not None and event_id is not None and tel_id is not None:
            self._push_lazy(kind, container, dict(obs_id=int(obs_id), event_id=int(event_id), tel_id=int(tel_id)))
            return
        self._push_event_row(kind, to_row(container, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_row(self, kind, row, *, obs_id=None, event_id=None, tel_id=None):
        """
        Push a row (a mapping ``{column: value}`` or an astropy table row). The stereo DL2 rows
        (``"dl2_stereo"``) need no ``tel_id``.
        """
        tel_id = SUBARRAY_ID if kind == "dl2_stereo" else tel_id
        self._push_event_row(kind, to_row(row, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_event(self, event, tel_ids=None, stereo=True):
        """
        Push the data of a ctapipe ``ArrayEventContainer``: the R0, R1, DL0, DL1, DL2 and
        trigger containers of its telescopes, and its stereo DL2.

        Parameters
        ----------
        event : ctapipe.containers.ArrayEventContainer
        tel_ids : iterable or None
            Telescopes whose data are pushed, all if None (e.g. the telescope of a mono stream).
        stereo : bool
            Push the stereo DL2 (False for a mono stream).
        """
        keys = dict(obs_id=event.index.obs_id, event_id=event.index.event_id)
        wanted = None if tel_ids is None else {int(t) for t in tel_ids}
        # the trigger first: it has the time of the event, used to count its levels in the rates
        for tel_id, container in event.trigger.tel.items():
            if wanted is None or tel_id in wanted:
                row = to_row(container, tel_id=tel_id, **keys)
                row.update(to_row({"event_type": event.trigger.event_type}))
                self._push_event_row("trigger", row)
        for kind in ("r0", "r1", "dl0", "dl1"):
            for tel_id, container in getattr(event, kind).tel.items():
                if wanted is None or tel_id in wanted:
                    self.push_container(kind, container, tel_id=tel_id, **keys)
        for tel_id, reconstructed in event.dl2.tel.items():
            row = container_row(reconstructed) if wanted is None or tel_id in wanted else None
            if row:
                self.push_row("dl2", row, tel_id=tel_id, **keys)
        if not stereo:
            return
        row = container_row(event.dl2.stereo, stereo=True)
        if row:
            # the time of the event, for the stereo rate (the telescopes have it in their trigger)
            self.push_row("dl2_stereo", {**row, "time": event.trigger.time}, **keys)

    def push_table(self, kind, table, *, obs_id=None, event_id=None, tel_id=None):
        """
        Push the rows of a table (an astropy table): all of them are processed at once, the
        DL1 and DL2 rows fill the statistics and every event of the table can be displayed.
        The stereo DL2 tables (``"dl2_stereo"``) need no ``tel_id``.
        """
        tel_id = SUBARRAY_ID if kind == "dl2_stereo" else tel_id
        columns = self._check(kind, to_columns(table, obs_id=obs_id, event_id=event_id, tel_id=tel_id))
        if columns is None:
            return
        now = time.monotonic()
        with self._lock:
            for tel_id, tel_columns in self._split_telescopes(columns):
                if kind in STATISTICS_KINDS:
                    tel_columns = self._telescope_frame(tel_id, tel_columns)
                    self._fill_statistics(kind, tel_id, tel_columns)
                tables = self._tables.setdefault(tel_id, _Tables())
                tables.add(kind, tel_columns, valid_rows(kind, tel_columns))
                if not self._events.get(tel_id):
                    # the events pushed one by one (a stream) stay the latest ones
                    self._latest[(tel_id, kind)] = (int(tel_columns["obs_id"][-1]),
                                                    int(tel_columns["event_id"][-1]))
                    self._latest_valid[(tel_id, kind)] = tables.last_valid_key(kind)
                self._count(tel_id, kind, n_rows(tel_columns), now)
            self.version += 1

    def _check(self, kind, columns):
        """The columns of pushed rows (None if there is no row), checked; DL2 with the viewer names"""
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}, known: {KINDS}")
        missing = [name for name in KEY_COLUMNS if name not in columns]
        if missing:
            raise ValueError(f"Missing columns {missing} in the {kind} data (or give them as keywords)")
        if kind == "dl2":
            columns = add_sst1mpipe_algorithm(columns)
        return columns if n_rows(columns) else None

    @staticmethod
    def _split_telescopes(columns):
        """(tel_id, columns of its rows) of the telescopes of the rows"""
        tel_ids = np.asarray(columns["tel_id"]).astype(int)
        unique = np.unique(tel_ids)
        if len(unique) == 1:
            yield int(unique[0]), columns
            return
        for tel_id in unique:
            yield int(tel_id), _select(columns, tel_ids == tel_id)

    def _count(self, tel_id, kind, n, now):
        """Count ``n`` rows received at ``now`` (monotonic time), for the table of the data received"""
        self._counts[(tel_id, kind)] += n
        arrivals = self._arrivals.setdefault((tel_id, kind), deque())
        # rows within 0.1 s are counted together, the arrivals out of the window are dropped:
        # the deque stays small whatever the rate and whether the rates are read or not
        if arrivals and now - arrivals[-1][0] < 0.1:
            arrivals[-1][1] += n
        else:
            arrivals.append([now, n])
        while arrivals and arrivals[0][0] < now - RATE_WINDOW:
            arrivals.popleft()

    def _count_valid(self, tel_id, key, kind, event_time):
        """
        A valid level of an event pushed: it is counted once in the rate history, at the time of the
        event. The time may come with another row of the event (e.g. its trigger): the levels
        received before wait for it.
        """
        self._latest_valid[(tel_id, kind)] = key
        events = self._rate_events.setdefault(tel_id, OrderedDict())
        entry = events.get(key)
        if (entry is not None and event_time is not None and entry[0] is not None
                and abs(event_time - entry[0]) > REPLAY_TIME_SHIFT):
            # the same ids at another time: the event of another pass of a replay in loop
            del events[key]
            entry = None
        if entry is None:
            entry = events[key] = [None, set(), set()]
            while len(events) > RATE_EVENTS:
                events.popitem(last=False)
        if entry[0] is None and event_time is not None:
            entry[0] = event_time
            self._last_time[tel_id] = max(event_time, self._last_time.get(tel_id, event_time))
            for waiting in entry[2]:
                self._add_to_history(tel_id, waiting, event_time)
            entry[1] |= entry[2]
            entry[2] = set()
        if kind in entry[1] or kind in entry[2]:
            return
        if entry[0] is None:
            entry[2].add(kind)
        else:
            entry[1].add(kind)
            self._add_to_history(tel_id, kind, entry[0])

    def _add_to_history(self, tel_id, kind, event_time):
        """Count a valid event in the rate history of a telescope and data level"""
        bins = self._history.setdefault((tel_id, kind), {})
        minute = int(event_time // RATE_BIN)
        bins[minute] = bins.get(minute, 0) + 1
        start = self._history_start.get((tel_id, kind))
        self._history_start[(tel_id, kind)] = event_time if start is None else min(start, event_time)
        if len(bins) > 2 * RATE_HISTORY_BINS:  # forget the old minutes
            for old in sorted(bins)[:-RATE_HISTORY_BINS]:
                del bins[old]

    def _keep_event(self, tel_id, key, kind, row):
        """Keep a row (or a `_LazyRow`) of a pushed event, in the last events of the telescope"""
        events = self._events.setdefault(tel_id, OrderedDict())
        event = events.get(key)
        if event is None:
            event = events[key] = {}
            while len(events) > self.max_events:
                events.popitem(last=False)
        else:
            # the events are ordered by their last update
            events.move_to_end(key)
        if kind in event:
            row = {**_as_row(event[kind]), **_as_row(row)}
        event[kind] = row
        self._latest[(tel_id, kind)] = key
        return row

    def _push_lazy(self, kind, container, keys):
        """Keep a container of an event, converted to a row only if the event is displayed"""
        now = time.monotonic()
        with self._lock:
            tel_id = keys["tel_id"]
            key = (keys["obs_id"], keys["event_id"])
            self._keep_event(tel_id, key, kind, _LazyRow(container, keys))
            if container_is_valid(kind, container):
                self._count_valid(tel_id, key, kind, _unix_time(getattr(container, "event_time", None)))
            self._count(tel_id, kind, 1, now)
            self.version += 1

    def _push_event_row(self, kind, row):
        """
        A row pushed event by event (the fast path of `_push_event_rows` for a single row): kept
        in the last events, counted in the rates if valid, DL1 / DL2 rows buffered for the statistics
        """
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}, known: {KINDS}")
        missing = [name for name in KEY_COLUMNS if name not in row]
        if missing:
            raise ValueError(f"Missing columns {missing} in the {kind} data (or give them as keywords)")
        if kind == "dl2":
            row = add_sst1mpipe_algorithm(row)
        now = time.monotonic()
        tel_id, key = int(row["tel_id"]), (int(row["obs_id"]), int(row["event_id"]))
        with self._lock:
            merged = self._keep_event(tel_id, key, kind, row)
            if row_is_valid(kind, merged):
                event_time = next((_unix_time(merged[name]) for name in TIME_COLUMNS if name in merged), None)
                self._count_valid(tel_id, key, kind, event_time)
            self._count(tel_id, kind, 1, now)
            if kind in STATISTICS_KINDS:
                # the statistics are filled later, in batches: only the columns they use are kept
                if kind in DL2_KINDS:
                    kept = {name: np.asarray(value)[np.newaxis] for name, value in row.items() if np.ndim(value) == 0}
                else:
                    needed = self._needed(kind)
                    kept = {name: np.asarray(value)[np.newaxis] for name, value in row.items()
                            if name in needed or name.startswith(CAMERA_FRAME_PREFIX)}
                self._pending.setdefault((kind, tel_id), []).append(kept)
                self._n_pending += 1
                if self._n_pending >= self.flush_size:
                    self._flush()
            self.version += 1

    def _push_event_rows(self, kind, columns):
        """Rows pushed event by event: kept as the last events, DL1 rows buffered for the statistics"""
        columns = self._check(kind, columns)
        if columns is None:
            return
        now = time.monotonic()
        with self._lock:
            tel_ids = np.asarray(columns["tel_id"]).astype(int)
            obs_ids = np.asarray(columns["obs_id"]).astype(int)
            event_ids = np.asarray(columns["event_id"]).astype(int)
            for i in range(len(tel_ids)):
                tel_id, key = int(tel_ids[i]), (int(obs_ids[i]), int(event_ids[i]))
                row = self._keep_event(tel_id, key, kind, _row(columns, i))
                if isinstance(row, dict) and row_is_valid(kind, row):
                    event_time = next((_unix_time(row[name]) for name in TIME_COLUMNS if name in row), None)
                    self._count_valid(tel_id, key, kind, event_time)
            for tel_id, tel_columns in self._split_telescopes(columns):
                self._count(tel_id, kind, n_rows(tel_columns), now)
                if kind in STATISTICS_KINDS:
                    self._buffer(kind, tel_id, tel_columns)
            if self._n_pending >= self.flush_size:
                self._flush()
            self.version += 1

    # ------------------------------------------------------------- statistics
    def _needed(self, kind):
        """Columns used by the statistics of a data level"""
        if kind not in self._needed_columns:
            statistics = build_statistics(self.statistics_configs[kind])
            names = {name for accumulator in statistics for name in accumulator.columns}
            self._needed_columns[kind] = names | {"tel_id", "obs_id", "event_id"}
        return self._needed_columns[kind]

    def _buffer(self, kind, tel_id, columns):
        """Keep rows pushed event by event for the statistics (only their columns used by the statistics)"""
        if kind in DL2_KINDS:
            # any algorithm can be plotted: all the columns with one value per row
            kept = {name: values for name, values in columns.items() if np.ndim(values) == 1}
        else:
            needed = self._needed(kind)
            # the parameters in the camera frame are kept to be converted to the telescope frame
            kept = {name: values for name, values in columns.items()
                    if name in needed or name.startswith(CAMERA_FRAME_PREFIX)}
        self._pending.setdefault((kind, tel_id), []).append(kept)
        self._n_pending += n_rows(columns)

    def _flush(self, tel_id=None, kind=None):
        """Fill the statistics with the buffered rows (of one telescope / data level, or of all)"""
        for key in list(self._pending):
            if (kind is not None and key[0] != kind) or (tel_id is not None and key[1] != tel_id):
                continue
            chunks = self._pending.pop(key)
            # rows with the same columns are filled together
            groups = {}
            for chunk in chunks:
                groups.setdefault(tuple(sorted(chunk)), []).append(chunk)
                self._n_pending -= n_rows(chunk)
            for names, group in groups.items():
                columns = {name: np.concatenate([chunk[name] for chunk in group]) for name in names}
                columns = self._telescope_frame(key[1], columns)
                self._fill_statistics(*key, columns)

    def _telescope_frame(self, tel_id, columns):
        """Telescope frame parameters from the camera frame parameters of sst1mpipe, if needed"""
        subarray = self.subarray
        if subarray is None or tel_id not in subarray.tel or "hillas_fov_lon" in columns:
            return columns
        return add_telescope_frame_parameters(columns, subarray.tel[tel_id].camera.geometry.frame)

    def _fill_statistics(self, kind, tel_id, columns):
        """Add rows to the statistics of a data level of a telescope"""
        if kind not in DL2_KINDS:
            self._tel_statistics(kind, tel_id, columns).fill(columns)
            return
        # DL2: one set of statistics per combination of the algorithms received so far, filled with
        # the generic columns of the algorithms of these rows (rows without the energy still fill
        # the histograms of the geometry, ...)
        algorithms = find_algorithms(columns, stereo=kind == "dl2_stereo")
        known = self._algorithms.setdefault((kind, tel_id), {})
        for group, names in algorithms.items():
            known[group] = sorted(set(known.get(group, [])) | set(names))
        for combination in combinations(known):
            generic = generic_columns(columns, algorithms, combination)
            # only the fields with one number per row are accumulated (not the lists of telescopes)
            generic = {name: values for name, values in generic.items()
                       if np.ndim(values) == 1 and np.asarray(values).dtype != object}
            if generic:
                self._tel_statistics(kind, tel_id, combination=combination_key(combination)).fill(generic)

    def _tel_statistics(self, kind, tel_id, columns=None, combination=None):
        """
        The statistics of a data level of a telescope (created at the first use); for the DL2, of a
        combination of algorithms (`sst1mpipe_viewer.dl2.combination_key`)
        """
        key = (kind, tel_id, combination)
        statistics = self._statistics.get(key)
        if statistics is None:
            statistics = build_statistics(self.statistics_configs[kind])
            self._statistics[key] = statistics
        return statistics

    # ----------------------------------------------------------------- output
    @property
    def tel_ids(self):
        """Telescopes of the subarray and of the data received"""
        with self._lock:
            ids = (set(self._events) | set(self._tables)) - {SUBARRAY_ID}
            if self.subarray is not None:
                ids |= set(self.subarray.tel_ids)
            return sorted(int(i) for i in ids)

    @property
    def event_tel_ids(self):
        """The telescopes, and `SUBARRAY_ID` if stereo events were received: all that have events to browse"""
        with self._lock:
            stereo = SUBARRAY_ID in self._events or SUBARRAY_ID in self._tables
        return self.tel_ids + ([SUBARRAY_ID] if stereo else [])

    @property
    def has_event_data(self):
        """Whether data were pushed event by event (else only tables, or nothing)"""
        with self._lock:
            return bool(self._events)

    def latest_key(self, tel_id, kind=None):
        """(obs_id, event_id) of the last event of a telescope (with data of ``kind`` if given)"""
        with self._lock:
            if kind is not None:
                return self._latest.get((tel_id, kind))
            events = self._events.get(tel_id)
            if events:
                return next(reversed(events))
            tables = self._tables.get(tel_id)
            return tables.keys[-1] if tables and tables.keys else None

    def latest_valid_key(self, tel_id, kind):
        """
        (obs_id, event_id) of the last event of a telescope whose data level ``kind`` is valid
        (`sst1mpipe_viewer.validity`), None if none
        """
        with self._lock:
            return self._latest_valid.get((tel_id, kind))

    def event_keys(self, tel_id):
        """(obs_id, event_id) of the events of a telescope: those of the tables, then the last ones pushed"""
        with self._lock:
            tables = self._tables.get(tel_id)
            keys = list(tables.keys) if tables else []
            known = tables.positions if tables else {}
            keys += [key for key in self._events.get(tel_id, ()) if key not in known]
            return keys

    def event_position(self, tel_id, key):
        """(position of ``key`` from 0 or None, number of events) in the `event_keys` of a telescope"""
        with self._lock:
            tables = self._tables.get(tel_id)
            known = tables.positions if tables else {}
            ring = [k for k in self._events.get(tel_id, ()) if k not in known]
            if key in known:
                position = known[key]
            elif key in ring:
                position = len(known) + ring.index(key)
            else:
                position = None
            return position, len(known) + len(ring)

    def event(self, tel_id, key, kinds=None):
        """
        Data of an event of a telescope.

        Parameters
        ----------
        tel_id : int
        key : tuple
            ``(obs_id, event_id)`` of the event.
        kinds : iterable or None
            Data levels to read (e.g. ``("r1", "trigger")``), all if None: only the rows of these
            levels are converted for the display.

        Returns
        -------
        dict
            ``{kind: row}``, empty if the event is unknown.
        """
        with self._lock:
            tables = self._tables.get(tel_id)
            result = tables.event(key, kinds) if tables is not None and key in tables.positions else {}
            pushed = self._events.get(tel_id, {}).get(key, {})
            for kind, row in pushed.items():
                if kinds is None or kind in kinds:
                    result[kind] = {**result.get(kind, {}), **_as_row(row)}
        for kind in ("dl1", "dl2"):
            row = result.get(kind)
            if row is not None and "hillas_fov_lon" not in row:
                result[kind] = self._converted_row(tel_id, key, kind, row)
        return result

    def _converted_row(self, tel_id, key, kind, row):
        """
        A row with the parameters of sst1mpipe in the camera frame, with their telescope frame values
        for the display. The conversion (astropy) is slow: the last rows converted are kept, all the
        pages showing the same events.
        """
        cache_key = (tel_id, key, kind, len(row))  # a row of an event merged with a new row is longer
        converted = self._converted.get(cache_key)
        if converted is None:
            columns = {name: np.asarray(value)[np.newaxis, ...] for name, value in row.items()}
            converted = {name: values[0] for name, values in self._telescope_frame(tel_id, columns).items()}
            self._converted[cache_key] = converted
            while len(self._converted) > CONVERTED_CACHE_SIZE:
                self._converted.pop(next(iter(self._converted)))
        return converted

    def counts(self):
        """Number of rows received, ``{(tel_id, kind): n}``"""
        with self._lock:
            return dict(self._counts)

    def rates(self):
        """Rates of rows received (Hz) over the last `RATE_WINDOW` seconds, ``{(tel_id, kind): rate}``"""
        now = time.monotonic()
        rates = {}
        with self._lock:
            for key, arrivals in self._arrivals.items():
                while arrivals and arrivals[0][0] < now - RATE_WINDOW:
                    arrivals.popleft()
                rates[key] = sum(n for _, n in arrivals) / RATE_WINDOW
        return rates

    def rate_history(self, tel_id, kind):
        """
        Rate of the rows of a telescope and data level in time, per minute.

        Only the events whose level is valid are counted (`sst1mpipe_viewer.validity`), at the
        time of the event (its trigger ``time`` or ``event_time``; the events without time are not
        counted). For the events pushed one by one: the last 24 hours, up to the last event pushed.

        Returns
        -------
        times, rates, errors : numpy arrays
            Centre of the bins (unix s), rates (rows per second) and their statistical
            uncertainties (see `sst1mpipe_viewer.rates`).
        """
        with self._lock:
            bins = self._history.get((tel_id, kind))
            if bins:
                return live_rates(bins, self._history_start[(tel_id, kind)], self._last_time[tel_id],
                                  max_bins=RATE_HISTORY_BINS)
            tables = self._tables.get(tel_id)
            if tables is None:
                return binned_rates(np.empty(0))
            cached = self._table_history.get((tel_id, kind))
            if cached is None or cached[0] != tables.version:
                cached = (tables.version, binned_rates(tables.event_times(kind)))
                self._table_history[(tel_id, kind)] = cached
            return cached[1]

    def event_time(self, tel_id, key):
        """
        Time of an event of a telescope (unix s), None if unknown: from the tables, or from the
        rows of the event pushed (``time`` of the trigger, ``event_time`` of the R0 / R1 / DL0).
        """
        if key is None:
            return None
        with self._lock:
            tables = self._tables.get(tel_id)
            value = tables.times.get(key) if tables is not None else None
            if value is None:
                for row in self._events.get(tel_id, {}).get(key, {}).values():
                    row = _as_row(row)
                    value = next((row[name] for name in TIME_COLUMNS if name in row), None)
                    if value is not None:
                        break
        return _unix_time(value)

    def algorithms(self, tel_id, kind="dl2"):
        """
        The DL2 algorithms received for a telescope (`SUBARRAY_ID` for the stereo DL2):
        ``{group: [algorithm, ...]}``, see `sst1mpipe_viewer.dl2`
        """
        with self._lock:
            self._flush(tel_id, kind)
            return {group: list(names) for group, names in self._algorithms.get((kind, tel_id), {}).items()}

    def statistics(self, tel_id, kind="dl1", algorithms=None):
        """
        Snapshot of the statistics of a data level of a telescope (see `StatisticsSet.snapshot`).

        Parameters
        ----------
        tel_id : int
            The telescope (`SUBARRAY_ID` for the stereo DL2).
        kind : str
            ``"dl1"``, ``"dl2"`` or ``"dl2_stereo"``.
        algorithms : dict or None
            For the DL2, the algorithm of each group ``{group: algorithm}``; the first algorithm
            (in alphabetical order) for the groups not given.
        """
        with self._lock:
            self._flush(tel_id, kind)
            combination = None
            if kind in DL2_KINDS:
                known = self._algorithms.get((kind, tel_id), {})
                chosen = {group: (algorithms or {}).get(group) for group in known}
                combination = combination_key({group: name if name in known[group] else known[group][0]
                                               for group, name in chosen.items()})
            return self._tel_statistics(kind, tel_id, combination=combination).snapshot()

    # ---------------------------------------------------------------- control
    def reset_statistics(self, tel_id=None, name=None, kind="dl1"):
        """Reset the statistics of a data level: of one accumulator ``name``, of a telescope, or of all"""
        with self._lock:
            # the buffered rows were received before the reset
            self._flush(tel_id, kind)
            for key, statistics in self._statistics.items():
                if key[0] == kind and tel_id in (None, key[1]):
                    statistics.reset(name)
            self.version += 1

    def clear(self):
        """Forget all the events and statistics"""
        with self._lock:
            self._clear()
            self.version += 1
        self.dl3.reset()



def _unix_time(value):
    """Unix time (s) of a time value (a number, an astropy ``Time``, or one of them in a 0-d array), None if unknown"""
    if value is None:
        return None
    if isinstance(value, np.ndarray) and value.dtype == object:
        value = value[()]
    try:
        if isinstance(value, Time):
            # for a UTC time, cheaper than Time.unix (the rates are filled for every event)
            value = (value.jd1 - 2440587.5 + value.jd2) * 86400.0 if value.scale == "utc" else value.unix
        value = float(value)
    except (TypeError, ValueError):
        return None
    # the unset times of ctapipe (NAN_TIME, MJD 0) are before the unix origin
    return value if np.isfinite(value) and value > 0 else None
