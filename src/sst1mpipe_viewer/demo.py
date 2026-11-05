"""
Demonstration feed: replay the events of a ctapipe HDF5 file (written by ``ctapipe-process``
or ``sst1mpipe-process``) into a `ViewerStore`, as rows (one event after the other at a given
rate, to simulate a live stream) or as whole tables.

This is not the interface between the pipeline and the viewer, only a way to show data.
"""

import threading

import tables
from astropy.table import join
from ctapipe.instrument import SubarrayDescription
from ctapipe.io import read_table

from .normalize import iter_rows, to_columns

__all__ = ["read_tables", "DemoFeed", "EventSourceFeed", "make_feed"]

KEYS = ["obs_id", "event_id", "tel_id"]


TELESCOPE_TABLES = (
    "/r1/event/telescope/tel_",
    "/dl0/event/telescope/tel_",
    "/dl1/event/telescope/images/tel_",
    "/dl1/event/telescope/parameters/tel_",
)


def read_tables(path, tel_ids=None):
    """
    Tables ``{(kind, tel_id): table}`` of the R1, DL0 and DL1 data and of the telescope
    triggers of a ctapipe HDF5 file (the DL1 images and parameters of an event are joined).
    """
    with tables.open_file(path) as h5file:
        paths = {node._v_pathname for node in h5file.walk_nodes("/", "Table")}
    file_tel_ids = {int(p.rsplit("_", 1)[1]) for p in paths if p.startswith(TELESCOPE_TABLES)}
    if tel_ids is not None:
        file_tel_ids &= set(tel_ids)

    result = {}
    for tel_id in sorted(file_tel_ids):
        for kind in ("r1", "dl0"):
            p = f"/{kind}/event/telescope/tel_{tel_id:03d}"
            if p in paths:
                result[(kind, tel_id)] = read_table(path, p)
        dl1 = [p for p in (f"/dl1/event/telescope/images/tel_{tel_id:03d}",
                           f"/dl1/event/telescope/parameters/tel_{tel_id:03d}") if p in paths]
        if len(dl1) == 2:
            result[("dl1", tel_id)] = join(read_table(path, dl1[0]), read_table(path, dl1[1]), keys=KEYS)
        elif dl1:
            result[("dl1", tel_id)] = read_table(path, dl1[0])
    if "/dl1/event/telescope/trigger" in paths:
        trigger = read_table(path, "/dl1/event/telescope/trigger")
        for tel_id in sorted(file_tel_ids):
            result[("trigger", tel_id)] = trigger[trigger["tel_id"] == tel_id]
    return result


class _ThreadedFeed:
    """Base of the feeds: ``run()`` pushes the data, `start` runs it in a background thread"""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def run(self):
        raise NotImplementedError

    def start(self):
        """Push the data in a background thread"""
        self._thread = threading.Thread(target=self.run, name="sst1mpipe-viewer-feed", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


class DemoFeed(_ThreadedFeed):
    """
    Replay a ctapipe HDF5 file into a store, in a background thread.

    Parameters
    ----------
    path : str or Path
        The HDF5 file.
    store : ViewerStore
        The store (its subarray is set from the file if it has none).
    rate : float
        Events per second; 0 pushes the whole tables at once.
    loop : bool
        Replay the file again when its end is reached.
    """

    def __init__(self, path, store, rate=5.0, loop=True, tel_ids=None):
        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.tables = read_tables(path, tel_ids)
        if store.subarray is None:
            store.set_subarray(SubarrayDescription.from_hdf(path))
        store.source_description = f"demo replay of {path}" + (f" at {self.rate:g} Hz" if self.rate else "")

    def events(self):
        """Rows of the file grouped by event, in the order of the events: lists of (kind, row)"""
        by_event = {}
        for (kind, _), table in self.tables.items():
            for row in iter_rows(to_columns(table)):
                key = (int(row["obs_id"]), int(row["event_id"]))
                by_event.setdefault(key, []).append((kind, row))
        return [by_event[key] for key in sorted(by_event)]

    def push_tables(self):
        for (kind, _), table in self.tables.items():
            self.store.push_table(kind, table)

    def run(self):
        """Push the data (blocking)"""
        if self.rate <= 0:
            self.push_tables()
            return
        events = self.events()
        while not self._stop.is_set():
            for rows in events:
                for kind, row in rows:
                    self.store.push_row(kind, row)
                if self._stop.wait(1.0 / self.rate):
                    return
            if not self.loop:
                return


class EventSourceFeed(_ThreadedFeed):
    """
    Read a file with a ctapipe ``EventSource`` (e.g. a simtel file, or a zfits file when
    sst1mpipe is installed), calibrate its events and compute their DL1 parameters
    (``CameraCalibrator`` and ``ImageProcessor`` with their default configuration) and push
    them into a store with `ViewerStore.push_event`, in a background thread. With ``rate`` 0,
    the events are pushed as fast as possible and the file is read only once.
    """

    def __init__(self, path, store, rate=5.0, loop=True, max_events=None):
        from ctapipe.io import EventSource

        super().__init__()
        self.path = path
        self.store = store
        self.rate = float(rate)
        self.loop = loop
        self.max_events = max_events
        with EventSource(path, max_events=1) as source:
            subarray = source.subarray
        if store.subarray is None:
            store.set_subarray(subarray)
        store.source_description = f"demo processing of {path}" + (f" at {self.rate:g} Hz" if self.rate else "")

    def run(self):
        from ctapipe.calib import CameraCalibrator
        from ctapipe.image import ImageProcessor
        from ctapipe.io import EventSource

        while not self._stop.is_set():
            with EventSource(self.path, max_events=self.max_events) as source:
                calibrator = CameraCalibrator(subarray=source.subarray)
                processor = ImageProcessor(subarray=source.subarray)
                for event in source:
                    calibrator(event)
                    processor(event)
                    self.store.push_event(event)
                    if self.rate > 0 and self._stop.wait(1.0 / self.rate):
                        return
                    if self._stop.is_set():
                        return
            if not self.loop or self.rate <= 0:
                return


def make_feed(path, store, rate=5.0, loop=True):
    """`DemoFeed` for a HDF5 file, `EventSourceFeed` for the other files"""
    if str(path).endswith((".h5", ".hdf5")):
        return DemoFeed(path, store, rate=rate, loop=loop)
    return EventSourceFeed(path, store, rate=rate, loop=loop)
