"""
Feeds of a `ViewerStore` from files, in a background thread:

- `HDF5Feed`: a ctapipe HDF5 file (written by ``ctapipe-process`` or ``sst1mpipe-process``),
  pushed as whole tables (all the events processed at once and browsable), or replayed event by
  event at a given rate to simulate a live stream;
- `EventSourceFeed`: a file read by a ctapipe ``EventSource`` (e.g. simtel), processed and pushed
  event by event.

They are not the interface between the pipeline (e.g. its ZMQ stream) and the viewer.
"""

import threading
import time

import tables
from astropy.table import join
from ctapipe.instrument import SubarrayDescription
from ctapipe.io import read_table

from .dl3 import read_dl3
from .normalize import iter_rows, to_columns

__all__ = ["read_tables", "HDF5Feed", "EventSourceFeed", "DL3Feed", "make_feed"]

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
DL2_GROUPS = ("energy", "classification", "geometry")


def read_tables(path, tel_ids=None):
    """
    Read the tables of a ctapipe HDF5 file.

    Parameters
    ----------
    path : str or Path
        The file (written by ``ctapipe-process`` or by sst1mpipe).
    tel_ids : iterable or None
        Telescopes to read, all if None.

    Returns
    -------
    dict
        ``{(kind, tel_id): astropy table}`` of the R0, R1, DL0, DL1 and DL2 data and of the
        telescope triggers. The DL1 images and parameters of an event are joined, and the DL2
        tables of ctapipe (energy, classification, geometry of each algorithm).
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


class HDF5Feed(_ThreadedFeed):
    """
    Push a ctapipe HDF5 file into a store.

    Parameters
    ----------
    path : str or Path
        The HDF5 file.
    store : ViewerStore
        The store (its subarray is set from the file if it has none).
    rate : float
        0 (default): the whole tables are pushed at once (`ViewerStore.push_table`: statistics
        of all the events, every event browsable). Otherwise the events are replayed one after
        the other at ``rate`` events per second (`ViewerStore.push_row`), as a live stream.
    loop : bool
        Replay the file again when its end is reached (with a rate).
    """

    def __init__(self, path, store, rate=0.0, loop=False, tel_ids=None):
        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.tel_ids = tel_ids
        self._tables = None
        store.add_telescopes(SubarrayDescription.from_hdf(path))
        if not store.source_description:
            store.source_description = f"replay of {path} at {self.rate:g} Hz" if self.rate > 0 else str(path)

    @property
    def tables(self):
        """Tables of the file, read at the first use (in the thread of the feed)"""
        if self._tables is None:
            self._tables = read_tables(self.path, self.tel_ids)
        return self._tables

    def events(self):
        """Rows of the file grouped by event, in the order of the events: lists of (kind, row)"""
        by_event = {}
        for (kind, _), table in self.tables.items():
            for row in iter_rows(to_columns(table)):
                key = (int(row["obs_id"]), int(row["event_id"]))
                by_event.setdefault(key, []).append((kind, row))
        return [by_event[key] for key in sorted(by_event)]

    def push_tables(self):
        """Push all the tables of the file at once (`ViewerStore.push_table`)"""
        for (kind, _), table in self.tables.items():
            self.store.push_table(kind, table)

    def run(self):
        """Push the data (blocking)"""
        if self.rate <= 0:
            self.push_tables()
            return
        events = self.events()
        pace = self._pace(self.rate)
        while not self._stop.is_set():
            for rows, _ in zip(events, pace):
                for kind, row in rows:
                    self.store.push_row(kind, row)
            if not self.loop or self._stop.is_set():
                return


class EventSourceFeed(_ThreadedFeed):
    """
    Read a file with a ctapipe ``EventSource`` (e.g. a simtel file, or a zfits file when
    sst1mpipe is installed), calibrate its events and compute their DL1 parameters
    (``CameraCalibrator`` and ``ImageProcessor`` with their default configuration) and push
    them into a store with `ViewerStore.push_event`, event by event. With ``rate`` 0, the events
    are pushed as fast as possible and the file is read only once.
    """

    def __init__(self, path, store, rate=0.0, loop=False, max_events=None):
        from ctapipe.io import EventSource

        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.max_events = max_events
        with EventSource(path, max_events=1) as source:
            subarray = source.subarray
        store.add_telescopes(subarray)
        if not store.source_description:
            store.source_description = f"processing of {path}" + (f" at {self.rate:g} Hz" if self.rate > 0 else "")

    def run(self):
        """Push the data (blocking; `start` runs it in a thread)"""
        from ctapipe.calib import CameraCalibrator
        from ctapipe.image import ImageProcessor
        from ctapipe.io import EventSource

        while not self._stop.is_set():
            with EventSource(self.path, max_events=self.max_events) as source:
                calibrator = CameraCalibrator(subarray=source.subarray)
                processor = ImageProcessor(subarray=source.subarray)
                pace = self._pace(self.rate) if self.rate > 0 else iter(int, 1)  # endless without rate
                for event, _ in zip(source, pace):
                    calibrator(event)
                    processor(event)
                    self.store.push_event(event)
                    if self._stop.is_set():
                        return
            if not self.loop or self.rate <= 0:
                return


class DL3Feed(_ThreadedFeed):
    """Push the events of a DL3 FITS file (`sst1mpipe_viewer.dl3`) into a store, at once"""

    def __init__(self, path, store):
        super().__init__()
        self.path = path
        self.store = store
        if not store.source_description:
            store.source_description = str(path)

    def run(self):
        """Read the file and push its events (blocking)"""
        self.store.dl3.push(*read_dl3(self.path))


def make_feed(path, store, rate=0.0, loop=False):
    """`HDF5Feed` for a HDF5 file, `DL3Feed` for a FITS file, `EventSourceFeed` for the other files"""
    if str(path).endswith((".h5", ".hdf5")):
        return HDF5Feed(path, store, rate=rate, loop=loop)
    if str(path).endswith((".fits", ".fits.gz")):
        return DL3Feed(path, store)
    return EventSourceFeed(path, store, rate=rate, loop=loop)
