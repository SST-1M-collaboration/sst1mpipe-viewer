"""Command line entry point: ``sst1mpipe-viewer``"""

import argparse
import importlib.util
import logging
import threading
from pathlib import Path

from ctapipe.instrument import SubarrayDescription

from .config import load_statistics_config
from .feeds import make_feed
from .server import serve
from .store import ViewerStore

__all__ = ["main", "default_subarray_file"]

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
        description="Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1, DL2) and of their accumulated statistics.",
    )
    parser.add_argument("--port", type=int, default=5006, help="port of the server (default: %(default)s)")
    parser.add_argument("--address", default=None, help="address of the server (default: all interfaces)")
    parser.add_argument("--allow-websocket-origin", action="append", default=None, metavar="HOST[:PORT]",
                        help="allowed websocket origin, e.g. calculus:5006 (repeatable)")
    parser.add_argument("files", nargs="*", type=Path, metavar="FILE",
                        help="files to show: ctapipe HDF5 files (e.g. of sst1mpipe-process), all their events"
                        " processed at once, DL3 FITS files (event lists),"
                        " or files read by a ctapipe EventSource (e.g. simtel), processed"
                        " event by event")
    parser.add_argument("--subarray", type=Path, default=None,
                        help="HDF5 file of the subarray description: camera geometries, positions of the"
                        " telescopes (default: the SST-1M subarray of sst1mpipe, sst1m_array.h5); the"
                        " telescopes of the files not in it are added")
    parser.add_argument("--statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL1 statistics (default: the one of the package)")
    parser.add_argument("--dl2-statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL2 statistics (default: the one of the package)")
    parser.add_argument("--dl3-statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated DL3 statistics (default: the one of the package)")
    parser.add_argument("--replay-rate", type=float, default=0.0, metavar="HZ",
                        help="push the events of the files one after the other at this rate (events per second),"
                        " as a live stream, instead of all at once")
    parser.add_argument("--loop", action="store_true", help="with --replay-rate, replay the files endlessly")
    parser.add_argument("--refresh-period", type=int, default=250,
                        help="period of the check for changes in ms (default: %(default)s)")
    parser.add_argument("--event-period", type=float, default=0.5,
                        help="minimum time between two displayed events of a stream in s (default: %(default)s)")
    parser.add_argument("--statistics-period", type=float, default=2.0,
                        help="minimum time between two refreshes of the statistics in s (default: %(default)s)")
    parser.add_argument("--colormap", default="inferno",
                        help="colormap of the cameras of the data (default: %(default)s)")
    parser.add_argument("--field-colormap", default="viridis",
                        help="colormap of the cameras of the per pixel fields (default: %(default)s)")
    parser.add_argument("--color-scale", choices=["lin", "log"], default="lin",
                        help="color scale of the cameras (default: %(default)s)")
    parser.add_argument("--show", action="store_true", help="open the viewer in a browser")
    return parser.parse_args(argv)


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
               "dl3": load_statistics_config(args.dl3_statistics_config, "dl3")}
    store = ViewerStore(subarray=subarray, statistics_configs=configs)
    if args.files:
        feeds = [make_feed(path, store, rate=args.replay_rate) for path in args.files]
        store.source_description = ", ".join(str(path) for path in args.files) + (
            f" (replay at {args.replay_rate:g} Hz)" if args.replay_rate > 0 else "")
        # the files are read one after the other, in the background: the server starts at once
        thread = threading.Thread(target=run_feeds, args=(feeds, args.loop and args.replay_rate > 0),
                                  name="sst1mpipe-viewer-files", daemon=True)
        thread.start()

    log.info("SST-1M viewer at http://%s:%d/", args.address or "localhost", args.port)
    serve(store, port=args.port, address=args.address, allow_websocket_origin=args.allow_websocket_origin,
          show=args.show, refresh_period=args.refresh_period, statistics_period=args.statistics_period,
          event_period=args.event_period, colormap=args.colormap, field_colormap=args.field_colormap,
          color_scale=args.color_scale)


def run_feeds(feeds, loop=False):
    """Run the feeds one after the other, endlessly with ``loop`` (the files replayed one after the other)"""
    while True:
        for feed in feeds:
            try:
                feed.run()
            except Exception:
                log.exception("Cannot read %s", feed.path)
        if not loop:
            return


if __name__ == "__main__":
    main()
