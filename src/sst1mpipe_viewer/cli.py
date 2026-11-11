"""Command line entry point: ``sst1mpipe-viewer``"""

import argparse
import importlib.util
import logging
import threading
from pathlib import Path

from ctapipe.instrument import SubarrayDescription

from .config import load_statistics_config
from .feeds import HDF5Feed, ReplayClock, is_zmq_endpoint, make_feed
from .server import serve
from .store import ViewerStore
from .sunset import SunsetReset

__all__ = ["main", "default_subarray_file", "make_streams", "run_streams"]

log = logging.getLogger("sst1mpipe_viewer")


def default_subarray_file():
    """The SST-1M subarray description of sst1mpipe (``sst1m_array.h5``), None if not installed"""
    spec = importlib.util.find_spec("sst1mpipe")  # does not import sst1mpipe
    if spec is None or not spec.submodule_search_locations:
        return None
    path = Path(next(iter(spec.submodule_search_locations))) / "resources" / "instrument" / "sst1m_array.h5"
    return path if path.is_file() else None


def parse_args(argv=None):
    """Options of the command line (``argv``: the arguments, those of the command if None)"""
    parser = argparse.ArgumentParser(
        prog="sst1mpipe-viewer",
        description="Bokeh viewer of the SST-1M events (R0 to DL3) and of their accumulated statistics. The data come"
        " either from one stream per telescope (mono mode: --tel1, --tel2) or from one stream of array events"
        " (stereo mode: --stereo).",
    )
    parser.add_argument("--port", type=int, default=5006, help="port of the server (default: %(default)s)")
    parser.add_argument("--address", default=None, help="address of the server (default: all interfaces)")
    parser.add_argument("--allow-websocket-origin", action="append", default=None, metavar="HOST[:PORT]",
                        help="allowed websocket origin, e.g. calculus:5006 (repeatable)")
    files = ("ctapipe HDF5 files (e.g. of sst1mpipe), DL3 FITS files (event lists), files read by a ctapipe"
             " EventSource (e.g. simtel), or the endpoint bound for the live stream of the pipeline"
             " (e.g. tcp://*:5561, to which sst1mpipe-process --publish connects)")
    parser.add_argument("--tel1", nargs="+", default=[], metavar="FILE_OR_URL",
                        help="mono mode: files of the stream of the first telescope of the subarray (only the data"
                        f" of this telescope are read, and no stereo data): {files}")
    parser.add_argument("--tel2", nargs="+", default=[], metavar="FILE_OR_URL",
                        help="mono mode: files of the stream of the second telescope of the subarray")
    parser.add_argument("--stereo", nargs="+", default=[], metavar="FILE_OR_URL",
                        help="stereo mode: files of the stream of complete array events (the data of the telescopes"
                        " and the stereo DL2), and stereo DL3 files; not with --tel1 / --tel2")
    parser.add_argument("--subarray", type=Path, default=None,
                        help="HDF5 file of the subarray description: camera geometries, positions of the"
                        " telescopes (default: the SST-1M subarray of sst1mpipe, sst1m_array.h5); the"
                        " telescopes of the files not in it are added")
    parser.add_argument("--statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL1 statistics (default: the one of the package)")
    parser.add_argument("--dl2-statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL2 statistics (default: the one of the package)")
    parser.add_argument("--dl2-stereo-statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated stereo DL2 statistics (default: the one of the"
                        " package)")
    parser.add_argument("--dl3-statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL3 statistics (default: the one of the package)")
    parser.add_argument("--replay-speed", type=float, default=0.0, metavar="FACTOR",
                        help="replay the events of the files in the order and at the pace of their timestamps, as"
                        " live streams (1: real time, 10: ten times faster), instead of all at once")
    parser.add_argument("--replay-rate", type=float, default=0.0, metavar="HZ",
                        help="push the events of the files one after the other at this rate (events per second),"
                        " as a live stream, instead of all at once")
    parser.add_argument("--loop", action="store_true",
                        help="replay the files endlessly (the timestamps are shifted at each pass)")
    parser.add_argument("--refresh-period", type=int, default=250,
                        help="period of the check for changes in ms (default: %(default)s)")
    parser.add_argument("--live-period", type=float, default=1.0,
                        help="Live mode: one event (the last received) is shown every this period in s, the same in"
                        " all the pages (default: %(default)s; also chosen in the pages)")
    parser.add_argument("--event-period", type=float, default=0.5,
                        help="minimum time between two refreshes of a page for new data (rates) in s"
                        " (default: %(default)s)")
    parser.add_argument("--statistics-period", type=float, default=2.0,
                        help="minimum time between two refreshes of the statistics in s (default: %(default)s)")
    parser.add_argument("--colormap", default="inferno",
                        help="colormap of the cameras of the data (default: %(default)s)")
    parser.add_argument("--field-colormap", default="viridis",
                        help="colormap of the cameras of the per pixel fields (default: %(default)s)")
    parser.add_argument("--color-scale", choices=["lin", "log"], default="lin",
                        help="color scale of the cameras (default: %(default)s)")
    parser.add_argument("--sunset-reset", choices=["auto", "on", "off"], default="auto",
                        help="reset all the plots at sunset at the site (from the system time): 'auto' with a live"
                             " stream (ZMQ endpoint) only (default: %(default)s)")
    parser.add_argument("--show", action="store_true", help="open the viewer in a browser")
    args = parser.parse_args(argv)
    if args.stereo and (args.tel1 or args.tel2):
        parser.error("--stereo (stream of array events) cannot be used with --tel1 / --tel2 (mono streams):"
                     " the events of the telescopes would be counted twice")
    if args.replay_speed > 0 and args.replay_rate > 0:
        parser.error("--replay-speed and --replay-rate cannot be used together")
    return args


def main(argv=None):
    """Start the viewer: read the subarray, start the feeds of the files, run the server"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)

    subarray_file = args.subarray or default_subarray_file()
    subarray = SubarrayDescription.from_hdf(subarray_file) if subarray_file else None
    if subarray is None:
        log.warning("No subarray description (sst1mpipe not installed and no --subarray): the subarray of"
                    " the files is used")
    else:
        log.info("Subarray %s (%s)", subarray.name, subarray_file)

    configs = {"dl1": load_statistics_config(args.statistics_config, "dl1"),
               "dl2": load_statistics_config(args.dl2_statistics_config, "dl2"),
               "dl2_stereo": load_statistics_config(args.dl2_stereo_statistics_config, "dl2_stereo"),
               "dl3": load_statistics_config(args.dl3_statistics_config, "dl3")}
    store = ViewerStore(subarray=subarray, statistics_configs=configs)
    streams = make_streams(args, store)
    if streams:
        # the files are read in the background: the server starts at once
        threading.Thread(target=run_streams, args=(streams, args.replay_speed, args.loop),
                         name="sst1mpipe-viewer-streams", daemon=True).start()

    live = any(is_zmq_endpoint(path) for path in [*args.tel1, *args.tel2, *args.stereo])
    if args.sunset_reset == "on" or (args.sunset_reset == "auto" and live):
        # a new night starts with empty plots
        SunsetReset(store).start()

    log.info("SST-1M viewer at http://%s:%d/", args.address or "localhost", args.port)
    serve(store, port=args.port, address=args.address, allow_websocket_origin=args.allow_websocket_origin,
          show=args.show, refresh_period=args.refresh_period, statistics_period=args.statistics_period,
          event_period=args.event_period, live_period=args.live_period, colormap=args.colormap,
          field_colormap=args.field_colormap, color_scale=args.color_scale)


def make_streams(args, store):
    """
    The streams of the command line.

    Parameters
    ----------
    args : argparse.Namespace
        Options with ``tel1``, ``tel2``, ``stereo`` (lists of files), ``replay_rate`` and ``loop``.
    store : ViewerStore
        The store filled by the streams (its ``source_description`` is set).

    Returns
    -------
    list of (str, list of feeds)
        Name and feeds of each stream: one per telescope in mono mode (its feeds push only the
        data of the telescope, and no stereo data), or the stream of array events in stereo mode.
    """
    if args.stereo:
        selections = [("stereo", args.stereo, None)]
    else:
        tel_ids = _stream_tel_ids(store, [*args.tel1, *args.tel2])
        selections = [(f"TEL {tel_id}", files, [tel_id])
                      for tel_id, files in zip(tel_ids, (args.tel1, args.tel2)) if files]
    streams = []
    for name, files, tel_ids in selections:
        feeds = [make_feed(path, store, rate=args.replay_rate, tel_ids=tel_ids, stereo=tel_ids is None)
                 for path in files]
        streams.append((name, feeds))
    replay = (f" (replay at {args.replay_rate:g} Hz)" if args.replay_rate > 0
              else f" (replay at speed {args.replay_speed:g})" if args.replay_speed > 0 else "")
    store.source_description = " &nbsp;|&nbsp; ".join(
        f"{name}: {', '.join(str(path) for path in files)}" for name, files, _ in selections) + replay
    return streams


def _stream_tel_ids(store, files):
    """The telescopes of the streams 1 and 2: the first two of the subarray (of the files if the store has none)"""
    if len(store.tel_ids) < 2:
        for path in files:
            if not is_zmq_endpoint(path) and str(path).endswith((".h5", ".hdf5")):
                store.add_telescopes(SubarrayDescription.from_hdf(path))
    tel_ids = store.tel_ids
    if len(tel_ids) < 2:
        raise SystemExit("The telescopes of --tel1 / --tel2 are unknown: give the subarray with --subarray")
    return tel_ids[:2]


def run_streams(streams, speed=0.0, loop=False):
    """
    Run the streams, each in its own thread (blocking until they end).

    Parameters
    ----------
    streams : list of (str, list of feeds)
        The streams (`make_streams`).
    speed : float
        Replay the events at the pace of their timestamps, with this speed factor: the streams
        share a clock (`sst1mpipe_viewer.feeds.ReplayClock`) and stay synchronous. 0: the feeds
        use their own setting (tables at once, or fixed rate).
    loop : bool
        Replay the files of each stream endlessly.
    """
    if speed > 0:
        replayed = [feed for _, feeds in streams for feed in feeds if isinstance(feed, HDF5Feed)]
        ranges = [time_range for feed in replayed if (time_range := feed.time_range()) is not None]
        if ranges:
            start, stop = min(r[0] for r in ranges), max(r[1] for r in ranges)
            clock = ReplayClock(start, stop - start, speed)
            for feed in replayed:
                feed.clock = clock
    threads = [threading.Thread(target=_run_stream, args=(name, feeds, loop), name=f"sst1mpipe-viewer-{name}",
                                daemon=True) for name, feeds in streams]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _run_stream(name, feeds, loop):
    """Run the feeds of a stream one after the other; with ``loop``, replay those which are replays endlessly"""
    pass_index = 0
    while True:
        replayed = False
        for feed in feeds:
            try:
                if getattr(feed, "is_replay", False):
                    feed.replay(pass_index)
                    replayed = True
                elif pass_index == 0:
                    feed.run()
            except Exception:
                log.exception("Stream %s: cannot read %s", name, feed.path)
        pass_index += 1
        if not (loop and replayed):
            return


if __name__ == "__main__":
    main()
