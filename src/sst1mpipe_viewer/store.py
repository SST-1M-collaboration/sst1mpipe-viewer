"""
Shared state of the viewer: the last events received and the accumulated statistics.

Any thread can push data to the store (``push_container``, ``push_row``, ``push_table``,
``push_event``); the bokeh sessions only read it. One store is shared by all the sessions
of a server, so that all the browsers show the same events and statistics (and a reset
resets them for everyone).

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

import numpy as np

from .accumulators import CameraAccumulator, Cut
from .config import build_statistics, load_statistics_config
from .normalize import KEY_COLUMNS, iter_rows, n_rows, to_columns

__all__ = ["KINDS", "ViewerStore"]

#: kinds of data accepted by the store
KINDS = ("r0", "r1", "dl0", "dl1", "trigger")

#: time window (s) of the rates of received rows
RATE_WINDOW = 10.0


class ViewerStore:
    """
    Last events and accumulated statistics of the telescopes.

    Parameters
    ----------
    subarray : ctapipe.instrument.SubarrayDescription or None
        Subarray of the data (camera geometries, telescope positions). It can be set later
        with `set_subarray`.
    statistics_config : dict or None
        Configuration of the statistics (`sst1mpipe_viewer.config.load_statistics_config`),
        the default one if None.
    max_events : int
        Number of events kept per telescope (for the event navigation).
    """

    def __init__(self, subarray=None, statistics_config=None, max_events=200):
        self._lock = threading.RLock()
        self.subarray = subarray
        self.statistics_config = statistics_config if statistics_config is not None else load_statistics_config()
        self.max_events = int(max_events)
        self.source_description = ""
        self.version = 0  # incremented at each change
        self._clear()

    def _clear(self):
        self._events = {}  # tel_id -> OrderedDict[(obs_id, event_id) -> {kind: row}]
        self._latest = {}  # (tel_id, kind) -> (obs_id, event_id)
        self._counts = Counter()  # (tel_id, kind) -> number of rows received
        self._arrivals = {}  # (tel_id, kind) -> deque of (time, n rows)
        self._statistics = {}  # tel_id -> StatisticsSet

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

    def push_container(self, kind, container, *, obs_id=None, event_id=None, tel_id=None):
        """Push a container of a telescope event (e.g. a ``DL1CameraContainer``)"""
        self._push(kind, to_columns(container, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_row(self, kind, row, *, obs_id=None, event_id=None, tel_id=None):
        """Push a row (a mapping ``{column: value}`` or an astropy table row)"""
        self._push(kind, to_columns(row, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

    def push_table(self, kind, table, *, obs_id=None, event_id=None, tel_id=None):
        """Push the rows of a table (an astropy table)"""
        self._push(kind, to_columns(table, obs_id=obs_id, event_id=event_id, tel_id=tel_id))

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
            self._push("trigger", columns)

    def _push(self, kind, columns):
        if kind not in KINDS:
            raise ValueError(f"Unknown kind {kind!r}, known: {KINDS}")
        missing = [name for name in KEY_COLUMNS if name not in columns]
        if missing:
            raise ValueError(f"Missing columns {missing} in the {kind} data (or give them as keywords)")
        n = n_rows(columns)
        if n == 0:
            return
        now = time.monotonic()
        with self._lock:
            for row in iter_rows(columns):
                tel_id = int(row["tel_id"])
                key = (int(row["obs_id"]), int(row["event_id"]))
                events = self._events.setdefault(tel_id, OrderedDict())
                event = events.get(key)
                if event is None:
                    event = events[key] = {}
                    while len(events) > self.max_events:
                        events.popitem(last=False)
                else:
                    # the events are ordered by their last update
                    events.move_to_end(key)
                event[kind] = {**event.get(kind, {}), **row}
                self._latest[(tel_id, kind)] = key

            tel_ids = np.asarray(columns["tel_id"]).astype(int)
            for tel_id in np.unique(tel_ids):
                tel_id = int(tel_id)
                selected = tel_ids == tel_id
                n_tel = int(np.count_nonzero(selected))
                self._counts[(tel_id, kind)] += n_tel
                arrivals = self._arrivals.setdefault((tel_id, kind), deque())
                arrivals.append((now, n_tel))
                if kind == "dl1":
                    tel_columns = columns if n_tel == n else {k: v[selected] for k, v in columns.items()}
                    self._tel_statistics(tel_id, tel_columns).fill(tel_columns)
            self.version += 1

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
            ids = set(self._events)
            if self.subarray is not None:
                ids |= set(self.subarray.tel_ids)
            return sorted(int(i) for i in ids)

    def latest_key(self, tel_id, kind=None):
        """(obs_id, event_id) of the last event of a telescope (with data of ``kind`` if given)"""
        with self._lock:
            if kind is not None:
                return self._latest.get((tel_id, kind))
            events = self._events.get(tel_id)
            return next(reversed(events)) if events else None

    def find_latest_key(self, tel_id, kind, predicate):
        """(obs_id, event_id) of the last event of a telescope whose ``kind`` row satisfies ``predicate(row)``"""
        with self._lock:
            for key, event in reversed(self._events.get(tel_id, {}).items()):
                row = event.get(kind)
                if row is not None and predicate(row):
                    return key
            return None

    def event_keys(self, tel_id):
        """(obs_id, event_id) of the events kept for a telescope, oldest first"""
        with self._lock:
            return list(self._events.get(tel_id, ()))

    def event(self, tel_id, key):
        """Data of an event of a telescope, ``{kind: row}`` (empty if unknown)"""
        with self._lock:
            return dict(self._events.get(tel_id, {}).get(key, {}))

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
            return self._tel_statistics(tel_id).snapshot()

    # ---------------------------------------------------------------- control
    def reset_statistics(self, tel_id=None, name=None):
        """Reset the statistics: of one accumulator ``name``, of a telescope, or of all of them"""
        with self._lock:
            tel_ids = list(self._statistics) if tel_id is None else [tel_id]
            for tel in tel_ids:
                self._tel_statistics(tel).reset(name)
            self.version += 1

    def set_cuts(self, cuts):
        """Set the cuts of the statistics of all the telescopes (and reset them)"""
        cuts = [str(Cut(c)) for c in cuts]  # validate before changing anything
        with self._lock:
            self.statistics_config = {**self.statistics_config, "cuts": cuts}
            for statistics in self._statistics.values():
                statistics.set_cuts(cuts)
            self.version += 1

    def clear(self):
        """Forget all the events and statistics"""
        with self._lock:
            self._clear()
            self.version += 1
