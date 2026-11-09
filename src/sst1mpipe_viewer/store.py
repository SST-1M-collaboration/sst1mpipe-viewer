"""
Shared state of the viewer: the events received and the accumulated statistics.

Any thread can push data to the store; the bokeh sessions only read it. One store is shared by
all the sessions of a server, so that all the browsers show the same events and statistics (and a
reset resets them for everyone).

Two ways of giving data
-----------------------
- **Event by event** (``push_event``, ``push_container``, ``push_row``), e.g. a live stream:
  the last ``max_events`` events of each telescope are kept for the display, the DL1 rows fill
  the statistics. Pushing is cheap (rates of several kHz): the statistics are filled in
  vectorized batches (when they are read, or every ``flush_size`` rows) and the parameters of
  sst1mpipe in the camera frame are converted when needed (`sst1mpipe_viewer.frames`).
- **Tables** (``push_table``), e.g. a file: all the rows are processed at once (vectorized) and
  every event of the tables can be displayed (``event_keys``, ``event``), not only the last ones.

Kinds of data
-------------
``r0``, ``r1``, ``dl0``, ``dl1`` and ``trigger``: the rows are those of the ctapipe tables
(``/r1/event/telescope/tel_XXX``, ``/dl1/event/telescope/images/tel_XXX`` and
``/dl1/event/telescope/parameters/tel_XXX``, ``/dl1/event/telescope/trigger``, ...) or the
flattened containers of these levels (`sst1mpipe_viewer.normalize.container_to_dict`).
Every row needs ``obs_id``, ``event_id`` and ``tel_id`` (given in the row or as keywords).
The rows of the same event (``obs_id``, ``event_id``) of a telescope are merged, e.g. a DL1
image row and a DL1 parameter row, or a R1 row and its trigger row.
"""

import threading
import time
from collections import Counter, OrderedDict, deque

import astropy.units as u
import numpy as np
from ctapipe.coordinates import GroundFrame
from ctapipe.instrument import SubarrayDescription

from .accumulators import CameraAccumulator, Cut
from .config import build_statistics, load_statistics_config
from .frames import CAMERA_FRAME_PREFIX, add_telescope_frame_parameters
from .normalize import KEY_COLUMNS, n_rows, to_columns

__all__ = ["KINDS", "ViewerStore"]

#: kinds of data accepted by the store
KINDS = ("r0", "r1", "dl0", "dl1", "trigger")

#: time window (s) of the rates of received rows
RATE_WINDOW = 10.0


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
        if self._row is None:
            columns = to_columns(self.container, **self.keys)
            self._row = _row(columns, 0)
            self.container = None
        return self._row


def _as_row(value):
    return value.row() if isinstance(value, _LazyRow) else value


def _row(columns, i):
    return {name: values[i] for name, values in columns.items()}


def _select(columns, mask):
    return {name: values[mask] for name, values in columns.items()}


class _Tables:
    """
    Events of a telescope given as tables: the columns of each kind and the row of each event,
    the events in the order of their first row.
    """

    def __init__(self):
        self.keys = []
        self.positions = {}  # key -> position in keys
        self.kinds = {}  # kind -> list of (columns, {key: row})

    def add(self, kind, columns):
        keys = list(zip(np.asarray(columns["obs_id"]).astype(int).tolist(),
                        np.asarray(columns["event_id"]).astype(int).tolist()))
        rows = {}
        for i, key in enumerate(keys):
            rows[key] = i
            if key not in self.positions:
                self.positions[key] = len(self.keys)
                self.keys.append(key)
        self.kinds.setdefault(kind, []).append((columns, rows))

    def event(self, key):
        result = {}
        for kind, tables in self.kinds.items():
            for columns, rows in tables:
                if key in rows:
                    result[kind] = {**result.get(kind, {}), **_row(columns, rows[key])}
        return result

    def last_key_with(self, kind, column):
        """Last key whose ``kind`` row has a finite ``column``"""
        best = None
        for columns, rows in self.kinds.get(kind, ()):
            if column not in columns:
                continue
            finite = np.flatnonzero(np.isfinite(np.asarray(columns[column], dtype=float)))
            if len(finite) == 0:
                continue
            key = (int(columns["obs_id"][finite[-1]]), int(columns["event_id"][finite[-1]]))
            if best is None or self.positions[key] > self.positions[best]:
                best = key
        return best


class ViewerStore:
    """
    Events and accumulated statistics of the telescopes.

    Parameters
    ----------
    subarray : ctapipe.instrument.SubarrayDescription or None
        Subarray of the data (camera geometries, telescope positions). It can be set later
        with `set_subarray`.
    statistics_config : dict or None
        Configuration of the statistics (`sst1mpipe_viewer.config.load_statistics_config`),
        the default one if None.
    max_events : int
        Number of events pushed event by event kept per telescope (for the display).
    flush_size : int
        Number of DL1 rows pushed event by event after which the statistics are filled.
    """

    def __init__(self, subarray=None, statistics_config=None, max_events=200, flush_size=2000):
        self._lock = threading.RLock()
        self.subarray = subarray
        self.statistics_config = statistics_config if statistics_config is not None else load_statistics_config()
        self.max_events = int(max_events)
        self.flush_size = int(flush_size)
        self.source_description = ""
        self.version = 0  # incremented at each change
        self._clear()

    def _clear(self):
        self._events = {}  # tel_id -> OrderedDict[(obs_id, event_id) -> {kind: row}], pushed event by event
        self._tables = {}  # tel_id -> _Tables, pushed as tables
        self._latest = {}  # (tel_id, kind) -> (obs_id, event_id)
        self._counts = Counter()  # (tel_id, kind) -> number of rows received
        self._arrivals = {}  # (tel_id, kind) -> deque of (time, n rows)
        self._statistics = {}  # tel_id -> StatisticsSet
        self._pending = {}  # tel_id -> list of DL1 columns not yet in the statistics
        self._n_pending = 0
        self._needed_columns = None

    # ------------------------------------------------------------------ input
    def set_subarray(self, subarray):
        """Set the subarray (camera geometries and positions of the telescopes)"""
        with self._lock:
            self.subarray = subarray
            # statistics created without the camera geometry have no camera maps: rebuild them
            for tel_id, statistics in list(self._statistics.items()):
                cameras = [a for a in statistics if isinstance(a, CameraAccumulator)]
                if any(a.n_pixels == 0 for a in cameras) and tel_id in subarray.tel:
                    del self._statistics[tel_id]
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
        self._push_event_rows(kind, to_columns(container, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_row(self, kind, row, *, obs_id=None, event_id=None, tel_id=None):
        """Push a row (a mapping ``{column: value}`` or an astropy table row)"""
        self._push_event_rows(kind, to_columns(row, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_event(self, event):
        """
        Push the data of a ctapipe ``ArrayEventContainer``: the R0, R1, DL0, DL1 and
        trigger containers of its telescopes.
        """
        keys = dict(obs_id=event.index.obs_id, event_id=event.index.event_id)
        for kind in ("r0", "r1", "dl0", "dl1"):
            for tel_id, container in getattr(event, kind).tel.items():
                self.push_container(kind, container, tel_id=tel_id, **keys)
        for tel_id, container in event.trigger.tel.items():
            columns = to_columns(container, tel_id=tel_id, **keys)
            columns.update(to_columns({"event_type": event.trigger.event_type}))
            self._push_event_rows("trigger", columns)

    def push_table(self, kind, table, *, obs_id=None, event_id=None, tel_id=None):
        """
        Push the rows of a table (an astropy table): all of them are processed at once, the
        DL1 rows fill the statistics and every event of the table can be displayed.
        """
        columns = self._check(kind, to_columns(table, obs_id=obs_id, event_id=event_id, tel_id=tel_id))
        if columns is None:
            return
        now = time.monotonic()
        with self._lock:
            for tel_id, tel_columns in self._split_telescopes(columns):
                if kind == "dl1":
                    tel_columns = self._telescope_frame(tel_id, tel_columns)
                    self._tel_statistics(tel_id, tel_columns).fill(tel_columns)
                self._tables.setdefault(tel_id, _Tables()).add(kind, tel_columns)
                if not self._events.get(tel_id):
                    # the events pushed one by one (a stream) stay the latest ones
                    self._latest[(tel_id, kind)] = (int(tel_columns["obs_id"][-1]),
                                                    int(tel_columns["event_id"][-1]))
                self._count(tel_id, kind, n_rows(tel_columns), now)
            self.version += 1

    def _check(self, kind, columns):
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}, known: {KINDS}")
        missing = [name for name in KEY_COLUMNS if name not in columns]
        if missing:
            raise ValueError(f"Missing columns {missing} in the {kind} data (or give them as keywords)")
        return columns if n_rows(columns) else None

    @staticmethod
    def _split_telescopes(columns):
        tel_ids = np.asarray(columns["tel_id"]).astype(int)
        unique = np.unique(tel_ids)
        if len(unique) == 1:
            yield int(unique[0]), columns
            return
        for tel_id in unique:
            yield int(tel_id), _select(columns, tel_ids == tel_id)

    def _count(self, tel_id, kind, n, now):
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

    def _push_lazy(self, kind, container, keys):
        now = time.monotonic()
        with self._lock:
            tel_id = keys["tel_id"]
            self._keep_event(tel_id, (keys["obs_id"], keys["event_id"]), kind, _LazyRow(container, keys))
            self._count(tel_id, kind, 1, now)
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
            # only the last max_events rows of each telescope can be kept
            for i in range(max(0, len(tel_ids) - self.max_events * len(set(tel_ids.tolist()))), len(tel_ids)):
                key = (int(obs_ids[i]), int(event_ids[i]))
                self._keep_event(int(tel_ids[i]), key, kind, _row(columns, i))
            for tel_id, tel_columns in self._split_telescopes(columns):
                self._count(tel_id, kind, n_rows(tel_columns), now)
                if kind == "dl1":
                    self._buffer(tel_id, tel_columns)
            if self._n_pending >= self.flush_size:
                self._flush()
            self.version += 1

    # ------------------------------------------------------------- statistics
    def _needed(self):
        """Columns used by the statistics (and to compute them in the telescope frame)"""
        if self._needed_columns is None:
            statistics = build_statistics(self.statistics_config, n_pixels=0)
            names = {name for accumulator in statistics for name in accumulator.columns}
            names |= {cut.column for cut in statistics.cuts}
            names |= {"tel_id", "obs_id", "event_id"}
            self._needed_columns = names
        return self._needed_columns

    def _buffer(self, tel_id, columns):
        needed = self._needed()
        kept = {name: values for name, values in columns.items()
                if name in needed or name.startswith(CAMERA_FRAME_PREFIX)}
        self._pending.setdefault(tel_id, []).append(kept)
        self._n_pending += n_rows(columns)

    def _flush(self, tel_id=None):
        """Fill the statistics with the buffered DL1 rows (of one telescope or of all)"""
        for tel in ([tel_id] if tel_id is not None else list(self._pending)):
            chunks = self._pending.pop(tel, [])
            # rows with the same columns are filled together
            groups = {}
            for chunk in chunks:
                groups.setdefault(tuple(sorted(chunk)), []).append(chunk)
                self._n_pending -= n_rows(chunk)
            for names, group in groups.items():
                columns = {name: np.concatenate([chunk[name] for chunk in group]) for name in names}
                columns = self._telescope_frame(tel, columns)
                self._tel_statistics(tel, columns).fill(columns)

    def _telescope_frame(self, tel_id, columns):
        """Telescope frame parameters from the camera frame parameters of sst1mpipe, if needed"""
        subarray = self.subarray
        if subarray is None or tel_id not in subarray.tel or "hillas_fov_lon" in columns:
            return columns
        return add_telescope_frame_parameters(columns, subarray.tel[tel_id].camera.geometry.frame)

    def _tel_statistics(self, tel_id, columns=None):
        statistics = self._statistics.get(tel_id)
        if statistics is None:
            n_pixels = 0
            if self.subarray is not None and tel_id in self.subarray.tel:
                n_pixels = self.subarray.tel[tel_id].camera.geometry.n_pixels
            elif columns is not None and "image" in columns:
                n_pixels = np.shape(columns["image"])[1]
            statistics = self._statistics[tel_id] = build_statistics(self.statistics_config, n_pixels)
        return statistics

    # ----------------------------------------------------------------- output
    @property
    def tel_ids(self):
        """Telescopes of the subarray and of the data received"""
        with self._lock:
            ids = set(self._events) | set(self._tables)
            if self.subarray is not None:
                ids |= set(self.subarray.tel_ids)
            return sorted(int(i) for i in ids)

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

    def find_latest_key(self, tel_id, kind, column):
        """(obs_id, event_id) of the last event of a telescope whose ``kind`` row has a finite ``column``"""
        columns = (column, CAMERA_FRAME_PREFIX + column)
        with self._lock:
            for key, event in reversed(self._events.get(tel_id, {}).items()):
                row = _as_row(event[kind]) if kind in event else None
                if row is not None and any(np.isfinite(float(row.get(c, np.nan))) for c in columns):
                    return key
            tables = self._tables.get(tel_id)
            if tables is None:
                return None
            for c in columns:
                key = tables.last_key_with(kind, c)
                if key is not None:
                    return key
            return None

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

    def event(self, tel_id, key):
        """Data of an event of a telescope, ``{kind: row}`` (empty if unknown)"""
        with self._lock:
            tables = self._tables.get(tel_id)
            result = tables.event(key) if tables is not None and key in tables.positions else {}
            pushed = self._events.get(tel_id, {}).get(key, {})
            for kind, row in pushed.items():
                result[kind] = {**result.get(kind, {}), **_as_row(row)}
        dl1 = result.get("dl1")
        if dl1 is not None and "hillas_fov_lon" not in dl1:
            # parameters in the camera frame (sst1mpipe): converted for the display
            columns = {name: np.asarray(value)[np.newaxis, ...] for name, value in dl1.items()}
            converted = self._telescope_frame(tel_id, columns)
            if converted is not columns:
                result["dl1"] = {name: values[0] for name, values in converted.items()}
        return result

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

    def statistics(self, tel_id):
        """Snapshot of the statistics of a telescope (see `StatisticsSet.snapshot`)"""
        with self._lock:
            self._flush(tel_id)
            return self._tel_statistics(tel_id).snapshot()

    # ---------------------------------------------------------------- control
    def reset_statistics(self, tel_id=None, name=None):
        """Reset the statistics: of one accumulator ``name``, of a telescope, or of all of them"""
        with self._lock:
            # the buffered rows were received before the reset
            if tel_id is None:
                self._flush()
            else:
                self._flush(tel_id)
            tel_ids = list(self._statistics) if tel_id is None else [tel_id]
            for tel in tel_ids:
                self._tel_statistics(tel).reset(name)
            self.version += 1

    def set_cuts(self, cuts):
        """Set the cuts of the statistics of all the telescopes (and reset them)"""
        cuts = [str(Cut(c)) for c in cuts]  # validate before changing anything
        with self._lock:
            self._flush()
            self.statistics_config = {**self.statistics_config, "cuts": cuts}
            self._needed_columns = None
            for statistics in self._statistics.values():
                statistics.set_cuts(cuts)
            self.version += 1

    def clear(self):
        """Forget all the events and statistics"""
        with self._lock:
            self._clear()
            self.version += 1
