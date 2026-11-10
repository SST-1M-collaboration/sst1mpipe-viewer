"""
DL3 data: lists of gamma-ray candidates of observations (GADF format, e.g. the FITS files written
by ``sst1mpipe_data_dl2_dl3``).

A DL3 file has an ``EVENTS`` table (``EVENT_ID``, ``TIME``, ``RA``, ``DEC``, ``ENERGY``, ``DETX``,
``DETY``) and a header describing the observation (``OBS_ID``, ``OBJECT``, ``RA_OBJ``, ``DEC_OBJ``,
``RA_PNT``, ``DEC_PNT``, ``LIVETIME``, ...). `DL3Data` accumulates the events of all the
observations pushed to it, per *series*: one per telescope for a mono analysis (one DL3 file per
telescope), or a single one for a stereo analysis.

The only values computed by the viewer are the positions of the events relative to the target of
their observation (``offset_lon``, ``offset_lat``, ``theta2``), once when the events are pushed.
The target is ``RA_OBJ`` / ``DEC_OBJ`` of the header, the pointing (``RA_PNT`` / ``DEC_PNT``) if
there is no target.
"""

import threading

import numpy as np
from astropy.table import Table

from .config import build_statistics, load_statistics_config
from .dl2 import SUBARRAY_ID
from .rates import binned_rates

__all__ = ["DL3Data", "read_dl3", "target_offsets", "unix_times"]

#: MJD of the origin of the unix times
UNIX_MJD = 40587.0


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

    The events are accumulated per *series*: the telescope of a mono analysis (one DL3 file per
    telescope), or `SUBARRAY_ID` for a stereo analysis.

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
        self._clear()

    def _clear(self):
        """Empty state: no event"""
        self._statistics = {}  # series -> StatisticsSet
        self._observations = {}  # (series, obs_id) -> summary (dict)
        self._times = {}  # series -> list of arrays of unix times of the events (one per push)
        self._rates = {}  # series -> cached (times, rates, errors)

    def push(self, events, header=None, series=SUBARRAY_ID):
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
        series : int
            The telescope of the events (mono analysis), `SUBARRAY_ID` for a stereo analysis.
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
            if series not in self._statistics:
                self._statistics[series] = build_statistics(self.config)
            if n:
                self._statistics[series].fill(columns)
            self._times.setdefault(series, []).append(times)
            self._rates.pop(series, None)
            obs_id = header.get("OBS_ID", len(self._observations))
            summary = self._observations.setdefault((series, obs_id), dict(series=series, obs_id=obs_id, n_events=0))
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

    def series(self):
        """The series with events (telescope ids, `SUBARRAY_ID`), sorted with the subarray last"""
        with self._lock:
            return sorted(self._statistics, key=lambda s: (s == SUBARRAY_ID, s))

    def observations(self):
        """Summaries of the observations received (list of dict, with their ``series``), in the order received"""
        with self._lock:
            return [dict(summary) for summary in self._observations.values()]

    def statistics(self, series=SUBARRAY_ID):
        """Snapshot of the histograms of a series (see `StatisticsSet.snapshot`), empty histograms if unknown"""
        with self._lock:
            statistics = self._statistics.get(series)
            return (statistics if statistics is not None else build_statistics(self.config)).snapshot()

    def rate_history(self, series=SUBARRAY_ID):
        """
        Rate of the events of a series in time, per minute: (centre of the bins in unix s, events
        per second, statistical uncertainties), see `sst1mpipe_viewer.rates`
        """
        with self._lock:
            if series not in self._rates:
                times = self._times.get(series)
                self._rates[series] = binned_rates(np.concatenate(times) if times else np.empty(0))
            return self._rates[series]

    def reset(self, name=None):
        """Forget the events received (or reset one histogram ``name`` only, for all the series)"""
        with self._lock:
            if name is None:
                self._clear()
            else:
                for statistics in self._statistics.values():
                    statistics.reset(name)
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

