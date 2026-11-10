"""
Publish the events of a file in the ZMQ stream of the pipeline, to test the viewer without the
pipeline: ``sst1mpipe-viewer-publish``.

The events of a ctapipe HDF5 file (e.g. the Mrk 421 test files) are sent as ``sst1mpipe-process
--publish`` sends them (``sst1mpipe.io.zmq_event_stream``): one message per telescope event and
one per stereo event, in the order of their timestamps, at their pace (``--speed``) or at a fixed
rate (``--rate``). The viewer binds the endpoint, the publisher connects to it::

    sst1mpipe-viewer --tel1 tcp://*:5561 --tel2 tcp://*:5562
    sst1mpipe-viewer-publish tests/data/mrk421_tel21.h5 --url tcp://localhost:5561 --speed 1 --loop
    sst1mpipe-viewer-publish tests/data/mrk421_tel22.h5 --url tcp://localhost:5562 --speed 1 --loop
"""

import argparse
import logging
import os
import socket
import time

import numpy as np

from .feeds import HDF5Feed
from .store import TIME_COLUMNS, ViewerStore

__all__ = ["FilePublisher", "main"]

log = logging.getLogger("sst1mpipe_viewer.publish")

#: the identifiers of a row, in the header of the messages
KEY_COLUMNS = ("obs_id", "event_id", "tel_id")


def event_messages(rows):
    """
    The contents of the messages of an event from its rows ``[(level, row), ...]`` (as read by
    `HDF5Feed.events`): ``[(topic, tel_id, levels), ...]`` with ``levels`` ``{level: fields}``
    """
    from sst1mpipe.io.zmq_event_stream import STEREO_TOPIC, telescope_topic

    by_telescope = {}
    for level, row in rows:
        tel_id = 0 if level == "dl2_stereo" else int(row["tel_id"])
        fields = {name: value for name, value in ((n, _plain(v)) for n, v in row.items() if n not in KEY_COLUMNS)
                  if value is not None}
        by_telescope.setdefault(tel_id, {}).setdefault(level, {}).update(fields)
    return [(STEREO_TOPIC if tel_id == 0 else telescope_topic(tel_id), tel_id, levels)
            for tel_id, levels in sorted(by_telescope.items())]


def _plain(value):
    """A number, a string or a numpy array (the values of a message), None if it cannot be sent"""
    if isinstance(value, np.ndarray):
        if value.dtype == object:
            return None
        return value.item() if value.ndim == 0 else value
    if isinstance(value, np.generic):
        return value.item()
    return value


class FilePublisher:
    """
    Publish the events of a file (see the module).

    Parameters
    ----------
    path : str or Path
        ctapipe HDF5 file.
    url : str
        Endpoint of the receiver (the viewer), to connect to.
    tel_ids : iterable or None
        Telescopes published, all if None.
    stereo : bool
        Publish the stereo DL2.
    """

    def __init__(self, path, url, tel_ids=None, stereo=True):
        import zmq

        self.feed = HDF5Feed(path, ViewerStore(), tel_ids=tel_ids, stereo=stereo)
        self.source = f"{socket.gethostname()}:{os.getpid()}:{path}"
        self.counts = {}
        self.socket = zmq.Context.instance().socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.connect(url)

    def publish(self, rows, shift=0.0):
        """Publish an event (its rows), its timestamps shifted by ``shift`` seconds"""
        from sst1mpipe.io.zmq_event_stream import encode

        key = rows[0][1]
        for topic, tel_id, levels in event_messages(rows):
            if shift:
                for fields in levels.values():
                    for name in TIME_COLUMNS:
                        if name in fields:
                            fields[name] = fields[name] + shift
            count = self.counts.get(topic, 0)
            self.socket.send_multipart(encode(topic, levels, key["obs_id"], key["event_id"], tel_id, self.source,
                                              count), copy=False)
            self.counts[topic] = count + 1

    def run(self, speed=1.0, rate=0.0, loop=False):
        """
        Publish the events, in the order of their timestamps: at their pace divided by ``speed``,
        or at ``rate`` events per second; endlessly with ``loop`` (timestamps shifted at each pass)
        """
        events = self.feed.events()
        time_range = self.feed.time_range()
        first, last = time_range if time_range else (0.0, 0.0)
        duration = max(last - first, 1.0)
        pass_index = 0
        while True:
            start = time.monotonic()
            for i, (event_time, rows) in enumerate(events):
                if rate > 0:
                    delay = i / rate - (time.monotonic() - start)
                elif np.isfinite(event_time):
                    delay = (event_time - first) / speed - (time.monotonic() - start)
                else:
                    delay = 0.0
                if delay > 0:
                    time.sleep(delay)
                self.publish(rows, shift=pass_index * duration)
            pass_index += 1
            log.info("%d events published (pass %d)", len(events), pass_index)
            if not loop:
                return

    def close(self):
        """Close the socket (the messages queued are sent first, at most 1 s)"""
        self.socket.close()


def main(argv=None):
    """Command line: ``sst1mpipe-viewer-publish FILE --url tcp://localhost:5561``"""
    parser = argparse.ArgumentParser(prog="sst1mpipe-viewer-publish", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="ctapipe HDF5 file")
    parser.add_argument("--url", required=True, help="endpoint of the viewer, e.g. tcp://localhost:5561")
    parser.add_argument("--tel-id", type=int, action="append", default=None,
                        help="telescope published (repeatable; all by default)")
    parser.add_argument("--no-stereo", action="store_true", help="do not publish the stereo DL2")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="pace of the timestamps: 1 real time, 10 ten times faster (default: %(default)s)")
    parser.add_argument("--rate", type=float, default=0.0, help="publish at this fixed rate (events/s) instead")
    parser.add_argument("--loop", action="store_true", help="publish the file endlessly")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    publisher = FilePublisher(args.file, args.url, tel_ids=args.tel_id, stereo=not args.no_stereo)
    # the receiver (the viewer) sends its subscription when the connection is made: wait a little
    time.sleep(0.5)
    try:
        publisher.run(speed=args.speed, rate=args.rate, loop=args.loop)
    except KeyboardInterrupt:
        pass
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
