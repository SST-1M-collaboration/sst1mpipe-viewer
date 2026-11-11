"""
Reset of the plots at sunset: a new night starts with empty statistics and rates.

The time of the next sunset at the site is computed with astropy from the system time
(`next_sunset`); `SunsetReset` then resets the store (`ViewerStore.reset`) when the system clock
reaches it, in a background thread.
"""

import logging
import threading
import time

import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time
from astropy.utils import iers

__all__ = ["SST1M_LOCATION", "SUNSET_ALTITUDE", "next_sunset", "SunsetReset"]

log = logging.getLogger("sst1mpipe_viewer.sunset")

#: site of the SST-1M telescopes (Ondřejov), used when the store has no subarray
SST1M_LOCATION = EarthLocation.from_geodetic(lon=14.782501 * u.deg, lat=49.912442 * u.deg, height=511.195 * u.m)
#: altitude of the centre of the Sun at sunset (refraction and radius of the Sun)
SUNSET_ALTITUDE = -0.833 * u.deg
#: step of the search of the sunset (s): the altitude is then interpolated
_STEP = 300.0


def next_sunset(location=SST1M_LOCATION, now=None):
    """
    Time of the next sunset at a location.

    Parameters
    ----------
    location : astropy.coordinates.EarthLocation
    now : float or None
        Unix time (s) from which the sunset is searched, the system time if None.

    Returns
    -------
    float or None
        Unix time (s) of the next sunset: the Sun going down through `SUNSET_ALTITUDE`; None if
        the Sun does not set in the next 2 days (polar day or night).
    """
    now = time.time() if now is None else float(now)
    times = now + np.arange(0.0, 2 * 86400.0 + _STEP, _STEP)
    # the precision of the Earth rotation tables does not matter here: no download
    with iers.conf.set_temp("auto_download", False), iers.conf.set_temp("auto_max_age", None):
        obstime = Time(times, format="unix")
        altitude = get_sun(obstime).transform_to(AltAz(obstime=obstime, location=location)).alt
    above = (altitude - SUNSET_ALTITUDE).to_value(u.deg)
    setting = np.flatnonzero((above[:-1] > 0) & (above[1:] <= 0))
    if len(setting) == 0:
        return None
    i = setting[0]
    return float(times[i] + _STEP * above[i] / (above[i] - above[i + 1]))


class SunsetReset:
    """
    Reset a store at each sunset, from the system time.

    Parameters
    ----------
    store : ViewerStore
        The store reset (`ViewerStore.reset`). Its ``next_reset_time`` is set to the time of the
        next sunset (unix s).
    location : astropy.coordinates.EarthLocation or None
        The site: by default the reference location of the subarray of the store, or the SST-1M site.
    clock : callable
        The system time (unix s), ``time.time`` by default.
    """

    #: longest time between two checks of the clock (s): the system time may be changed
    CHECK_PERIOD = 30.0

    def __init__(self, store, location=None, clock=time.time):
        self.store = store
        if location is None:
            subarray = store.subarray
            location = subarray.reference_location if subarray is not None else SST1M_LOCATION
        self.location = location
        self.clock = clock
        self._stop = threading.Event()
        self._thread = None
        self.next_time = None
        self._schedule(self.clock())

    def _schedule(self, now):
        """Find the next sunset after ``now``"""
        self.next_time = next_sunset(self.location, now)
        self.store.next_reset_time = self.next_time
        if self.next_time is None:
            log.warning("No sunset in the next 2 days at the site: no automatic reset of the plots")
        else:
            log.info("The plots will be reset at sunset, %s UTC", Time(self.next_time, format="unix").isot[:19])

    def check(self, now=None):
        """
        Reset the store if the sunset is reached, then wait for the next one.

        Returns
        -------
        bool
            Whether the store was reset.
        """
        now = self.clock() if now is None else now
        if self.next_time is None:
            self._schedule(now)
            return False
        if now < self.next_time:
            return False
        log.info("Sunset: the plots are reset")
        self.store.reset()
        # the next sunset: after this one (a minute later, not to find the same one again)
        self._schedule(max(now, self.next_time + 60.0))
        return True

    def run(self):
        """Check the clock until stopped (blocking; `start` runs it in a thread)"""
        while not self._stop.is_set():
            self.check()
            remaining = self.CHECK_PERIOD if self.next_time is None else self.next_time - self.clock()
            self._stop.wait(min(max(remaining, 0.5), self.CHECK_PERIOD))

    def start(self):
        """Check the clock in a background thread"""
        self._thread = threading.Thread(target=self.run, name="sst1mpipe-viewer-sunset", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop the thread"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
