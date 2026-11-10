"""
Feeds of a `ViewerStore` from files, in background threads.

Streams
-------
The viewer has two modes (`sst1mpipe_viewer.cli`):

- **mono**: one stream per telescope. A feed then pushes only the data of its telescope
  (``tel_ids``) and no stereo data (``stereo=False``);
- **stereo**: one stream of complete array events (the data of the telescopes and the stereo
  DL2): a feed pushes everything.

Feeds
-----
- `HDF5Feed`: a ctapipe HDF5 file (written by ``ctapipe-process`` or sst1mpipe), pushed as whole
  tables (all the events processed at once and browsable), or replayed event by event in the order
  of the timestamps of the events to simulate a live stream;
- `EventSourceFeed`: a file read by a ctapipe ``EventSource`` (e.g. simtel), processed and pushed
  event by event;
- `DL3Feed`: a DL3 FITS file (event list), pushed at once.

Replay
------
A replay is paced either at a fixed rate (``rate`` events per second) or by the timestamps of the
events (`ReplayClock`, shared by the streams so that they stay synchronous: an event is pushed
when the clock reaches its time). When a file is replayed again (``loop``), the timestamps of its
events are shifted by the duration of the replay, so that the time keeps increasing.

They are not the interface between the pipeline (e.g. its ZMQ stream) and the viewer.
"""

import threading
import time

import numpy as np
import tables
from astropy.table import join
from ctapipe.instrument import SubarrayDescription
from ctapipe.io import read_table

from .dl2 import SUBARRAY_ID
from .dl3 import read_dl3
from .normalize import iter_rows, to_columns
from .store import TIME_COLUMNS

__all__ = ["read_tables", "ReplayClock", "HDF5Feed", "EventSourceFeed", "DL3Feed", "make_feed"]

KEYS = ["obs_id", "event_id", "tel_id"]


TELESCOPE_TABLES = (
    "/r0/event/telescope/tel_",
    "/r1/event/telescope/tel_",
    "/dl0/event/telescope/tel_",
    "/dl1/event/telescope/images/tel_",
    "/dl1/event/telescope/parameters/tel_",
    "/dl2/event/telescope/",
)

#: DL2 tables of ctapipe, ``/dl2/event/telescope/<group>/<algorithm>/tel_XXX``
DL2_GROUPS = ("geometry", "energy", "classification", "particle_type", "impact", "disp")
#: stereo DL2 tables of ctapipe, ``/dl2/event/subarray/<group>/<algorithm>``
STEREO_KEYS = ["obs_id", "event_id"]


def read_tables(path, tel_ids=None, stereo=True):
    """
    Read the tables of a ctapipe HDF5 file.

    Parameters
    ----------
    path : str or Path
        The file (written by ``ctapipe-process`` or by sst1mpipe).
    tel_ids : iterable or None
        Telescopes to read, all if None.
    stereo : bool
        Read the stereo DL2 tables (not for the stream of a single telescope).

    Returns
    -------
    dict
        ``{(kind, tel_id): astropy table}`` of the R0, R1, DL0, DL1 and DL2 data and of the
        telescope triggers. The DL1 images and parameters of an event are joined, and the DL2
        tables of ctapipe (geometry, energy, classification, impact, disp of each algorithm).
        The stereo DL2 tables are joined in ``("dl2_stereo", SUBARRAY_ID)``, with the subarray
        trigger (the times of the events) in ``("trigger", SUBARRAY_ID)``.
    """
    with tables.open_file(path) as h5file:
        paths = {node._v_pathname for node in h5file.walk_nodes("/", "Table")}
    file_tel_ids = {int(p.rsplit("_", 1)[1]) for p in paths if p.startswith(TELESCOPE_TABLES)}
    if tel_ids is not None:
        file_tel_ids &= set(tel_ids)

    result = {}
    for tel_id in sorted(file_tel_ids):
        for kind in ("r0", "r1", "dl0"):
            p = f"/{kind}/event/telescope/tel_{tel_id:03d}"
            if p in paths:
                result[(kind, tel_id)] = read_table(path, p)
        dl1 = [p for p in (f"/dl1/event/telescope/images/tel_{tel_id:03d}",
                           f"/dl1/event/telescope/parameters/tel_{tel_id:03d}") if p in paths]
        if len(dl1) == 2:
            result[("dl1", tel_id)] = join(read_table(path, dl1[0]), read_table(path, dl1[1]), keys=KEYS)
        elif dl1:
            result[("dl1", tel_id)] = read_table(path, dl1[0])
        dl2 = _read_dl2(path, paths, tel_id)
        if dl2 is not None:
            result[("dl2", tel_id)] = dl2
    if "/dl1/event/telescope/trigger" in paths:
        trigger = read_table(path, "/dl1/event/telescope/trigger")
        for tel_id in sorted(file_tel_ids):
            result[("trigger", tel_id)] = trigger[trigger["tel_id"] == tel_id]
    if not stereo:
        return result
    stereo = None
    for p in sorted(paths):
        parts = p.split("/")  # "", "dl2", "event", "subarray", group, algorithm
        if len(parts) == 6 and p.startswith("/dl2/event/subarray/") and parts[4] in DL2_GROUPS:
            other = read_table(path, p)
            stereo = other if stereo is None else join(stereo, other, keys=STEREO_KEYS)
    if stereo is not None:
        result[("dl2_stereo", SUBARRAY_ID)] = stereo
        if "/dl1/event/subarray/trigger" in paths:
            trigger = read_table(path, "/dl1/event/subarray/trigger")
            trigger["tel_id"] = SUBARRAY_ID
            result[("trigger", SUBARRAY_ID)] = trigger
    return result


def _read_dl2(path, paths, tel_id):
    """DL2 table of a telescope: of sst1mpipe, or the DL2 tables of ctapipe joined (None if none)"""
    name = f"tel_{tel_id:03d}"
    sst1mpipe = f"/dl2/event/telescope/parameters/{name}"
    if sst1mpipe in paths:
        return read_table(path, sst1mpipe)
    table = None
    for p in sorted(paths):
        parts = p.split("/")  # "", "dl2", "event", "telescope", group, algorithm, tel_XXX
        if len(parts) == 7 and p.startswith("/dl2/event/telescope/") and parts[4] in DL2_GROUPS and parts[6] == name:
            other = read_table(path, p)
            table = other if table is None else join(table, other, keys=KEYS)
    return table


class ReplayClock:
    """
    Clock of a replay paced by the timestamps of the events, shared by the streams.

    Parameters
    ----------
    start_time : float
        Timestamp (unix s) of the first event of all the streams: the origin of the replay.
    duration : float
        Duration (s) of the data of all the streams: the shift of the timestamps at each new pass
        of a replay in loop.
    speed : float
        1 for real time, 10 for ten times faster, ...
    """

    def __init__(self, start_time, duration, speed=1.0):
        self.start_time = float(start_time)
        self.duration = max(float(duration), 1.0)
        self.speed = float(speed)
        self._origin = time.monotonic()

    def delay(self, event_time):
        """Time to wait (s) before pushing an event of timestamp ``event_time`` (negative if late)"""
        return (event_time - self.start_time) / self.speed - (time.monotonic() - self._origin)


class _ThreadedFeed:
    """Base of the feeds: ``run()`` pushes the data, `start` runs it in a background thread"""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def _pace(self, rate):
        """Generator waiting between the events to push them at ``rate`` Hz; stops when stopped"""
        period = 1.0 / rate
        next_time = time.monotonic()
        while True:
            yield
            next_time += period
            delay = next_time - time.monotonic()
            if delay < -1.0:
                # too late (the pushing is slower than the rate): do not catch up
                next_time = time.monotonic()
            if self._stop.wait(max(delay, 0.0)) or self._stop.is_set():
                return

    def run(self):
        """Push the data (blocking; `start` runs it in a thread)"""
        raise NotImplementedError

    def start(self):
        """Push the data in a background thread"""
        self._thread = threading.Thread(target=self.run, name="sst1mpipe-viewer-feed", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop the feed and wait for its thread"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


def _row_time(rows):
    """Timestamp (unix s) of an event from its rows ``[(kind, row), ...]``, NaN if none has a time"""
    for _, row in rows:
        for name in TIME_COLUMNS:
            if name in row:
                try:
                    return float(row[name])
                except (TypeError, ValueError):
                    pass
    return np.nan


class HDF5Feed(_ThreadedFeed):
    """
    Push a ctapipe HDF5 file into a store.

    Parameters
    ----------
    path : str or Path
        The HDF5 file.
    store : ViewerStore
        The store (the telescopes of the file are added to its subarray).
    rate : float
        Replay the events one after the other at ``rate`` events per second, as a live stream.
    loop : bool
        Replay the file again when its end is reached.
    tel_ids : iterable or None
        Telescopes whose data are pushed, all if None (the stream of a telescope pushes only its own).
    stereo : bool
        Push the stereo DL2 (False for the stream of a telescope).
    clock : ReplayClock or None
        Replay the events at the times given by this clock from their timestamps (instead of ``rate``).

    Without ``rate`` nor ``clock``, the whole tables are pushed at once (`ViewerStore.push_table`:
    statistics of all the events, every event browsable).
    """

    def __init__(self, path, store, rate=0.0, loop=False, tel_ids=None, stereo=True, clock=None):
        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.tel_ids = tel_ids
        self.stereo = stereo
        self.clock = clock
        self._tables = None
        self._events = None
        store.add_telescopes(SubarrayDescription.from_hdf(path))
        if not store.source_description:
            store.source_description = f"replay of {path}" if self.is_replay else str(path)

    @property
    def is_replay(self):
        """Whether the events are replayed one by one (else the tables are pushed at once)"""
        return self.rate > 0 or self.clock is not None

    @property
    def tables(self):
        """Tables of the file, read at the first use (in the thread of the feed)"""
        if self._tables is None:
            self._tables = read_tables(self.path, self.tel_ids, stereo=self.stereo)
        return self._tables

    def events(self):
        """
        The events of the file in the order of their timestamps (then of their ids): a list of
        ``(timestamp, rows)``, the rows of an event being ``[(kind, row), ...]`` with the row
        carrying its time first. In a stream of array events, an event has the rows of all its
        telescopes and its stereo row.
        """
        if self._events is None:
            by_event = {}
            for (kind, _), table in self.tables.items():
                for row in iter_rows(to_columns(table)):
                    key = (int(row["obs_id"]), int(row["event_id"]))
                    by_event.setdefault(key, []).append((kind, row))
            events = []
            for key, rows in by_event.items():
                # the rows with the time of the event first: the store then knows the time of the event
                rows.sort(key=lambda item: not any(name in item[1] for name in TIME_COLUMNS))
                events.append((_row_time(rows), key, rows))
            events.sort(key=lambda event: (np.nan_to_num(event[0], nan=np.inf), event[1]))
            self._events = [(event_time, rows) for event_time, _, rows in events]
        return self._events

    def time_range(self):
        """(first, last) timestamps (unix s) of the events of the file, None if they have no time"""
        times = np.array([event_time for event_time, _ in self.events()], dtype=float)
        times = times[np.isfinite(times)]
        return (float(times.min()), float(times.max())) if len(times) else None

    def push_tables(self):
        """Push all the tables of the file at once (`ViewerStore.push_table`)"""
        for (kind, _), table in self.tables.items():
            self.store.push_table(kind, table)

    def replay(self, pass_index=0):
        """
        Push the events one by one, once.

        Parameters
        ----------
        pass_index : int
            Number of times the data were already replayed: the timestamps are shifted by this
            number of durations of the replay, so that the time keeps increasing in a loop.
        """
        events = self.events()
        time_range = self.time_range()
        if self.clock is not None:
            shift = pass_index * self.clock.duration
        else:
            # replay of this file alone: its own duration (at least 1 s between two passes)
            shift = pass_index * max(time_range[1] - time_range[0], 1.0) if time_range else 0.0
        pace = self._pace(self.rate) if self.clock is None else None
        for event_time, rows in events:
            if self._stop.is_set():
                return
            if pace is not None:
                if next(pace, self) is self:  # stopped
                    return
            elif np.isfinite(event_time):
                delay = self.clock.delay(event_time + shift)
                if delay > 0 and self._stop.wait(delay):
                    return
            for kind, row in rows:
                if shift:
                    row = {name: value + shift if name in TIME_COLUMNS else value for name, value in row.items()}
                self.store.push_row(kind, row)

    def run(self):
        """Push the data (blocking): the tables at once, or the replay of the events (endless with ``loop``)"""
        if not self.is_replay:
            self.push_tables()
            return
        pass_index = 0
        while not self._stop.is_set():
            self.replay(pass_index)
            pass_index += 1
            if not self.loop:
                return


class EventSourceFeed(_ThreadedFeed):
    """
    Read a file with a ctapipe ``EventSource`` (e.g. a simtel file, or a zfits file when
    sst1mpipe is installed), calibrate its events and compute their DL1 parameters
    (``CameraCalibrator`` and ``ImageProcessor`` with their default configuration) and push
    them into a store with `ViewerStore.push_event`, event by event. With ``rate`` 0, the events
    are pushed as fast as possible and the file is read only once. ``tel_ids`` and ``stereo``
    select what is pushed, as for `HDF5Feed`.
    """

    def __init__(self, path, store, rate=0.0, loop=False, max_events=None, tel_ids=None, stereo=True):
        from ctapipe.io import EventSource

        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.max_events = max_events
        self.tel_ids = tel_ids
        self.stereo = stereo
        with EventSource(path, max_events=1) as source:
            subarray = source.subarray
        store.add_telescopes(subarray)
        if not store.source_description:
            store.source_description = f"processing of {path}" + (f" at {self.rate:g} Hz" if self.rate > 0 else "")

    def replay(self, pass_index=0):
        """Read, process and push the events of the file once (the timestamps are not shifted)"""
        from ctapipe.calib import CameraCalibrator
        from ctapipe.image import ImageProcessor
        from ctapipe.io import EventSource

        with EventSource(self.path, max_events=self.max_events) as source:
            calibrator = CameraCalibrator(subarray=source.subarray)
            processor = ImageProcessor(subarray=source.subarray)
            pace = self._pace(self.rate) if self.rate > 0 else iter(int, 1)  # endless without rate
            for event, _ in zip(source, pace):
                calibrator(event)
                processor(event)
                self.store.push_event(event, tel_ids=self.tel_ids, stereo=self.stereo)

    def run(self):
        """Push the events (blocking), endlessly with ``loop`` and a rate"""
        pass_index = 0
        while not self._stop.is_set():
            self.replay(pass_index)
            pass_index += 1
            if not self.loop or self.rate <= 0:
                return


class DL3Feed(_ThreadedFeed):
    """
    Push the events of a DL3 FITS file (`sst1mpipe_viewer.dl3`) into a store, at once.

    Parameters
    ----------
    path : str or Path
        The DL3 file.
    store : ViewerStore
    series : int
        The telescope of the events (mono analysis), `SUBARRAY_ID` for a stereo analysis.
    """

    def __init__(self, path, store, series=SUBARRAY_ID):
        super().__init__()
        self.path = path
        self.store = store
        self.series = series
        if not store.source_description:
            store.source_description = str(path)

    def run(self):
        """Read the file and push its events (blocking)"""
        self.store.dl3.push(*read_dl3(self.path), series=self.series)


def is_dl3_file(path):
    """Whether a file is a DL3 event list (a FITS file)"""
    return str(path).endswith((".fits", ".fits.gz"))


def make_feed(path, store, rate=0.0, loop=False, tel_ids=None, stereo=True, clock=None):
    """
    Feed of a file: `DL3Feed` for a FITS file, `HDF5Feed` for a HDF5 file, `EventSourceFeed` for
    the other files. ``tel_ids`` and ``stereo`` select what is pushed (see the module): for a DL3
    file, the events are those of the telescope ``tel_ids[0]``, of the subarray if None.
    """
    if is_dl3_file(path):
        return DL3Feed(path, store, series=SUBARRAY_ID if tel_ids is None else list(tel_ids)[0])
    if str(path).endswith((".h5", ".hdf5")):
        return HDF5Feed(path, store, rate=rate, loop=loop, tel_ids=tel_ids, stereo=stereo, clock=clock)
    return EventSourceFeed(path, store, rate=rate, loop=loop, tel_ids=tel_ids, stereo=stereo)
