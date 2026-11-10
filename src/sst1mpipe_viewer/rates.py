"""
Rates in time: number of rows (events) per second, in bins of one minute, with their statistical
uncertainty.

A bin with ``n`` rows observed during ``duration`` seconds has a rate ``n / duration`` and an
uncertainty ``sqrt(n) / duration`` (Poisson statistics). The duration of the first and last bins
is the part of the minute covered by the data, so that their rate is not underestimated.
"""

import numpy as np

__all__ = ["RATE_BIN", "binned_rates", "live_rates"]

#: duration of the bins (s)
RATE_BIN = 60.0
#: shortest duration used to compute a rate (s): a bin just started has a huge uncertainty anyway
MIN_DURATION = 1.0

_EMPTY = (np.empty(0), np.empty(0), np.empty(0))


def _rates(starts, stops, counts):
    """(centre of the bins, rates, uncertainties) of counts observed between ``starts`` and ``stops``"""
    counts = np.asarray(counts, dtype=float)
    durations = np.maximum(stops - starts, MIN_DURATION)
    return (starts + stops) / 2, counts / durations, np.sqrt(counts) / durations


def binned_rates(times, bin_width=RATE_BIN, max_bins=2000):
    """
    Rates of events from their times (e.g. the events of a file).

    Parameters
    ----------
    times : array
        Times of the events (unix s); the non finite ones are ignored.
    bin_width : float
        Duration of the bins (s). The bins are longer if there would be more than ``max_bins``.
    max_bins : int
        Maximum number of bins.

    Returns
    -------
    times, rates, errors : arrays
        Centre of the bins (unix s), rates (events per second) and their uncertainties.
    """
    times = np.asarray(times, dtype=float)
    times = times[np.isfinite(times)]
    if len(times) == 0:
        return _EMPTY
    first, last = float(times.min()), float(times.max())
    start = np.floor(first / bin_width) * bin_width
    width = bin_width * max(1, int(np.ceil((last - start) / bin_width / max_bins)))
    edges = start + width * np.arange(int((last - start) // width) + 2)
    counts, _ = np.histogram(times, bins=edges)
    # the first and last bins are only covered from the first to the last event
    return _rates(np.maximum(edges[:-1], first), np.minimum(edges[1:], last), counts)


def live_rates(counts, first, now, bin_width=RATE_BIN, max_bins=1440):
    """
    Rates of rows counted as they arrive (a stream), up to now: the minutes without any row have
    a rate of 0, the current minute is included (with the time elapsed so far).

    Parameters
    ----------
    counts : dict
        ``{bin index: number of rows}``, the index of a bin being ``int(time // bin_width)``.
    first : float
        Time of arrival of the first row (unix s).
    now : float
        Current time (unix s).
    bin_width : float
        Duration of the bins (s).
    max_bins : int
        Only the last ``max_bins`` bins are returned.

    Returns
    -------
    times, rates, errors : arrays
        Centre of the bins (unix s), rates (rows per second) and their uncertainties.
    """
    if not counts:
        return _EMPTY
    last_index = int(now // bin_width)
    first_index = max(int(first // bin_width), last_index - max_bins + 1)
    indices = np.arange(first_index, last_index + 1)
    n = np.array([counts.get(int(i), 0) for i in indices])
    starts = np.maximum(indices * bin_width, first)
    stops = np.minimum((indices + 1) * bin_width, max(now, first))
    return _rates(starts, stops, n)
