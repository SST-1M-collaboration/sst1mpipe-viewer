"""Reset of the plots at sunset"""

import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time

from sst1mpipe_viewer.store import ViewerStore
from sst1mpipe_viewer.sunset import SST1M_LOCATION, SUNSET_ALTITUDE, SunsetReset, next_sunset

# 2026-01-20 12:00 UTC: the Sun sets at Ondrejov at about 15:35 UTC
NOON = Time("2026-01-20T12:00:00").unix


def sun_altitude(unix_time, location=SST1M_LOCATION):
    obstime = Time(unix_time, format="unix")
    return get_sun(obstime).transform_to(AltAz(obstime=obstime, location=location)).alt


def test_next_sunset():
    sunset = next_sunset(now=NOON)
    assert Time("2026-01-20T15:20:00").unix < sunset < Time("2026-01-20T15:50:00").unix
    # the Sun is at the sunset altitude, going down
    assert abs(sun_altitude(sunset) - SUNSET_ALTITUDE) < 0.01 * u.deg
    assert sun_altitude(sunset - 600) > SUNSET_ALTITUDE > sun_altitude(sunset + 600)
    # after the sunset: the one of the next day
    following = next_sunset(now=sunset + 60)
    assert 23.9 * 3600 < following - sunset < 24.1 * 3600


def test_no_sunset_in_the_polar_night():
    assert next_sunset(EarthLocation.from_geodetic(0 * u.deg, 89 * u.deg), now=Time("2026-01-01T00:00:00").unix) is None


def test_sunset_reset():
    """the store is reset when the system time reaches the sunset, once per sunset"""
    store = ViewerStore()
    now = [NOON]
    sunset_reset = SunsetReset(store, clock=lambda: now[0])
    first = sunset_reset.next_time
    assert store.next_reset_time == first == next_sunset(now=NOON)
    assert not sunset_reset.check() and store.reset_time is None

    now[0] = first + 1
    assert sunset_reset.check() and store.reset_time is not None
    # the next sunset is scheduled: no second reset this evening
    assert sunset_reset.next_time - first > 23 * 3600 and store.next_reset_time == sunset_reset.next_time
    assert not sunset_reset.check()
    now[0] = sunset_reset.next_time
    assert sunset_reset.check()


def test_sunset_reset_thread():
    store = ViewerStore()
    now = [NOON]
    sunset_reset = SunsetReset(store, clock=lambda: now[0])
    now[0] = sunset_reset.next_time + 1
    sunset_reset.start()
    try:
        for _ in range(200):
            if store.reset_time is not None:
                break
            sunset_reset._stop.wait(0.05)
        assert store.reset_time is not None
    finally:
        sunset_reset.stop()
