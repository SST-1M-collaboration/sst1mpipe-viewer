"""Command line entry point: ``sst1mpipe-viewer``"""

import argparse
import importlib.util
import logging
from pathlib import Path

from ctapipe.instrument import SubarrayDescription

from .config import load_statistics_config
from .demo import make_feed
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
    parser = argparse.ArgumentParser(
        prog="sst1mpipe-viewer",
        description="Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1) and of their accumulated statistics.",
    )
    parser.add_argument("--port", type=int, default=5006, help="port of the server (default: %(default)s)")
    parser.add_argument("--address", default=None, help="address of the server (default: all interfaces)")
    parser.add_argument("--allow-websocket-origin", action="append", default=None, metavar="HOST[:PORT]",
                        help="allowed websocket origin, e.g. calculus:5006 (repeatable)")
    parser.add_argument("--subarray", type=Path, default=None,
                        help="HDF5 file of the subarray description (default: the demo file's, or sst1mpipe's)")
    parser.add_argument("--statistics-config", type=Path, default=None,
                        help="YAML configuration of the accumulated statistics")
    parser.add_argument("--demo", type=Path, default=None, metavar="FILE",
                        help="replay the events of a ctapipe HDF5 file (DL1 with images, optionally R1/DL0),"
                        " or process a file read by a ctapipe EventSource (e.g. simtel)")
    parser.add_argument("--rate", type=float, default=5.0,
                        help="events per second of the demo, 0 for the whole file at once (default: %(default)s)")
    parser.add_argument("--no-loop", action="store_true", help="replay the demo file only once")
    parser.add_argument("--refresh-period", type=int, default=1000,
                        help="period of the refresh of the displays in ms (default: %(default)s)")
    parser.add_argument("--statistics-period", type=float, default=2.0,
                        help="minimum time between two refreshes of the statistics in s (default: %(default)s)")
    parser.add_argument("--show", action="store_true", help="open the viewer in a browser")
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)

    # without --subarray, the subarray of the demo file is used (set by the feed)
    subarray_file = args.subarray or (None if args.demo else default_subarray_file())
    subarray = SubarrayDescription.from_hdf(subarray_file) if subarray_file else None
    if subarray is None and args.demo is None:
        log.warning("No subarray description: the cameras and the array cannot be displayed")

    store = ViewerStore(subarray=subarray, statistics_config=load_statistics_config(args.statistics_config))
    if args.demo is not None:
        make_feed(args.demo, store, rate=args.rate, loop=not args.no_loop).start()

    log.info("SST-1M viewer at http://%s:%d/", args.address or "localhost", args.port)
    serve(store, port=args.port, address=args.address, allow_websocket_origin=args.allow_websocket_origin,
          show=args.show, refresh_period=args.refresh_period, statistics_period=args.statistics_period)


if __name__ == "__main__":
    main()
