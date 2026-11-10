"""
DL3 data: lists of gamma-ray candidates of observations (GADF format, e.g. the FITS files written
by ``sst1mpipe_data_dl2_dl3``).

A DL3 file has an ``EVENTS`` table (``EVENT_ID``, ``TIME``, ``RA``, ``DEC``, ``ENERGY``, ``DETX``,
``DETY``) and a header describing the observation (``OBS_ID``, ``OBJECT``, ``RA_OBJ``, ``DEC_OBJ``,
``RA_PNT``, ``DEC_PNT``, ``LIVETIME``, ...). Unlike the other data levels, the DL3 are not per
telescope: `DL3Data` accumulates the events of all the observations pushed to it.

The only values computed by the viewer are the positions of the events relative to the target of
their observation (``offset_lon``, ``offset_lat``, ``theta2``), once when the events are pushed.
The target is ``RA_OBJ`` / ``DEC_OBJ`` of the header, the pointing (``RA_PNT`` / ``DEC_PNT``) if
there is no target.
"""

import threading

import numpy as np
from astropy.table import Table

from .config import build_statistics, load_statistics_config

__all__ = ["DL3Data", "read_dl3", "target_offsets", "unix_times"]

#: MJD of the origin of the unix times
UNIX_MJD = 40587.0
#: maximum number of bins of the rate of the events in time
MAX_RATE_BINS = 500


def read_dl3(path):
    """
    Read a DL3 FITS file.

    Returns
    -------
    events : astropy.table.Table
        The ``EVENTS`` table.
    header : dict
        The header of the ``EVENTS`` table (``OBS_ID``, ``OBJECT``, ``RA_OBJ``, ...).
    """
    events = Table.read(path, hdu="EVENTS")
    return events, dict(events.meta)


def unix_times(times, header):
    """
    Unix times (s) of the ``TIME`` of DL3 events, counted in seconds from the reference MJD of the
    header (``MJDREFI`` + ``MJDREFF``; the unix origin if missing, as written by sst1mpipe). The
    time system of the file (e.g. TAI) is kept: no leap second correction.
    """
    reference = float(header.get("MJDREFI", UNIX_MJD)) + float(header.get("MJDREFF", 0.0))
    return np.asarray(times, dtype=float) + (reference - UNIX_MJD) * 86400.0


def target_offsets(ra, dec, target_ra, target_dec):
    """
    Positions relative to a target, in the plane tangent to the sky at the target.

    Parameters
    ----------
    ra, dec : arrays
        Positions of the events (deg).
    target_ra, target_dec : float
        Position of the target (deg).

    Returns
    -------
    offset_lon, offset_lat : arrays
        Offsets towards increasing RA and Dec (deg).
    theta2 : array
        Squared angular distance to the target (deg^2).
    """
    ra, dec = np.deg2rad(np.asarray(ra, dtype=float)), np.deg2rad(np.asarray(dec, dtype=float))
    ra0, dec0 = np.deg2rad(float(target_ra)), np.deg2rad(float(target_dec))
    delta = ra - ra0
    cos_distance = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(delta)
    with np.errstate(invalid="ignore", divide="ignore"):
        # gnomonic projection (only meaningful on the hemisphere of the target)
        lon = np.where(cos_distance > 0, np.cos(dec) * np.sin(delta) / cos_distance, np.nan)
        lat = np.where(cos_distance > 0, (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(delta))
                       / cos_distance, np.nan)
    theta = np.rad2deg(np.arccos(np.clip(cos_distance, -1.0, 1.0)))
    return np.rad2deg(lon), np.rad2deg(lat), theta**2


class DL3Data:
    """
    The DL3 events received: accumulated histograms (energy, theta^2, sky map, field of view),
    a summary of each observation and the rate of the events in time.

    Parameters
    ----------
    config : dict or None
        Statistics configuration (`sst1mpipe_viewer.config`), the default DL3 one if None.
    on_change : callable or None
        Called after each change (the store uses it to refresh the pages).
    """

    def __init__(self, config=None, on_change=None):
        self.config = config if config is not None else load_statistics_config(kind="dl3")
        self._on_change = on_change
        self._lock = threading.Lock()
        self._statistics = build_statistics(self.config, n_pixels=0)
        self._observations = {}  # obs_id -> summary (dict)
        self._times = []  # unix times of the events, one array per push
        self._rates = None  # cached (times, rates)

    def push(self, events, header=None):
        """
        Add the events of an observation.

        Parameters
        ----------
        events : astropy.table.Table or dict
            The ``EVENTS`` table (GADF columns, any letter case). ``RA``, ``DEC``, ``ENERGY`` in
            deg and TeV, or as quantities.
        header : dict or None
            Header of the table (``OBS_ID``, ``OBJECT``, ``RA_OBJ``, ``DEC_OBJ``, ``LIVETIME``, ...);
            the ``meta`` of the table if None.
        """
        events = events if isinstance(events, Table) else Table(events)
        header = dict(events.meta) if header is None else dict(header)
        columns = {}
        for name in events.colnames:
            column = events[name]
            unit = {"ra": "deg", "dec": "deg", "detx": "deg", "dety": "deg", "energy": "TeV"}.get(name.lower())
            if unit is not None and getattr(column, "unit", None) is not None:
                columns[name.lower()] = np.asarray(column.quantity.to_value(unit), dtype=float)
            else:
                columns[name.lower()] = np.asarray(column)
        n = len(events)
        target = _target(header)
        if target is not None and "ra" in columns and "dec" in columns:
            columns["offset_lon"], columns["offset_lat"], columns["theta2"] = target_offsets(
                columns["ra"], columns["dec"], *target)
        times = unix_times(columns["time"], header) if "time" in columns else np.empty(0)

        with self._lock:
            if n:
                self._statistics.fill(columns)
            self._times.append(times)
            self._rates = None
            obs_id = header.get("OBS_ID", len(self._observations))
            summary = self._observations.setdefault(obs_id, dict(obs_id=obs_id, n_events=0))
            summary["n_events"] += n
            summary.update(
                object=str(header.get("OBJECT", "")),
                target=target,
                pointing=_position(header, "RA_PNT", "DEC_PNT"),
                livetime=_number(header.get("LIVETIME")),
                start=float(np.nanmin(times)) if len(times) else np.nan,
                stop=float(np.nanmax(times)) if len(times) else np.nan,
            )
        if self._on_change is not None:
            self._on_change()

    def observations(self):
        """Summaries of the observations received (list of dict), in the order received"""
        with self._lock:
            return [dict(summary) for summary in self._observations.values()]

    def statistics(self):
        """Snapshot of the histograms (see `StatisticsSet.snapshot`)"""
        with self._lock:
            return self._statistics.snapshot()

    def rate_history(self):
        """Rate of the events in time: (start of the bins in unix s, events per second)"""
        with self._lock:
            if self._rates is None:
                self._rates = _rates(np.concatenate(self._times) if self._times else np.empty(0))
            return self._rates

    def reset(self, name=None):
        """Forget the events received (or reset one histogram ``name`` only)"""
        with self._lock:
            self._statistics.reset(name)
            if name is None:
                self._observations = {}
                self._times = []
                self._rates = None
        if self._on_change is not None:
            self._on_change()


def _number(value):
    """Float of a header value, NaN if missing or not a number"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _position(header, ra_key, dec_key):
    """(ra, dec) in deg of two header keys, None if missing"""
    ra, dec = _number(header.get(ra_key)), _number(header.get(dec_key))
    return (ra, dec) if np.isfinite(ra) and np.isfinite(dec) else None


def _target(header):
    """Position (ra, dec) of the target of an observation: its object, else its pointing, else None"""
    return _position(header, "RA_OBJ", "DEC_OBJ") or _position(header, "RA_PNT", "DEC_PNT")


def _rates(times):
    """Events per second in at most `MAX_RATE_BINS` bins of time: (start of the bins, rates)"""
    times = times[np.isfinite(times)]
    if len(times) == 0:
        return np.empty(0), np.empty(0)
    start, stop = float(times.min()), float(times.max())
    n_bins = int(min(MAX_RATE_BINS, max(1, np.sqrt(len(times)))))
    edges = np.linspace(start, max(stop, start + 1.0), n_bins + 1)
    counts, _ = np.histogram(times, bins=edges)
    return edges[:-1], counts / np.diff(edges)
