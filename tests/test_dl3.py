import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.table import Table
from conftest import Browser

from sst1mpipe_viewer.dl3 import DL3Data, read_dl3, target_offsets, unix_times
from sst1mpipe_viewer.feeds import make_feed
from sst1mpipe_viewer.store import ViewerStore

HEADER = dict(OBS_ID=7, OBJECT="Mrk 421", RA_OBJ=166.1, DEC_OBJ=38.2, RA_PNT=166.1, DEC_PNT=38.9, LIVETIME=100.0)


def events_table(n=200, seed=0):
    rng = np.random.default_rng(seed)
    return Table(dict(EVENT_ID=np.arange(n), TIME=np.linspace(1000.0, 1100.0, n),
                      RA=166.1 + rng.normal(0, 0.3, n), DEC=38.2 + rng.normal(0, 0.3, n),
                      ENERGY=10 ** rng.normal(0, 0.3, n), DETX=rng.normal(0, 1, n), DETY=rng.normal(0, 1, n)))


def test_target_offsets_against_astropy():
    ra, dec = np.array([166.5, 165.0, 166.1]), np.array([38.0, 39.0, 38.2])
    lon, lat, theta2 = target_offsets(ra, dec, 166.1, 38.2)
    target = SkyCoord(166.1, 38.2, unit="deg")
    separation = target.separation(SkyCoord(ra, dec, unit="deg")).deg
    assert np.allclose(theta2, separation**2)
    assert np.allclose(np.hypot(lon, lat), np.rad2deg(np.tan(np.deg2rad(separation))))
    assert lon[0] > 0 and lat[0] < 0 and lon[1] < 0 and lat[1] > 0
    assert theta2[2] == 0


def test_unix_times():
    assert unix_times([10.0], {}).tolist() == [10.0]  # sst1mpipe: seconds from the unix origin
    assert unix_times([10.0], {"MJDREFI": 40588, "MJDREFF": 0.5}).tolist() == [10.0 + 1.5 * 86400]


def test_dl3_data():
    changes = []
    data = DL3Data(on_change=lambda: changes.append(1))
    data.push(events_table(), HEADER)
    data.push(events_table(50, seed=1), HEADER)
    (observation,) = data.observations()
    assert observation["obs_id"] == 7 and observation["n_events"] == 250 and observation["target"] == (166.1, 38.2)
    accumulators = data.statistics()["accumulators"]
    assert accumulators["energy"]["n_entries"] == 250
    assert accumulators["theta2"]["n_entries"] == 250 and accumulators["sky"]["counts"].sum() > 200
    times, rates = data.rate_history()
    assert np.isclose((rates * (times[1] - times[0])).sum(), 250)
    data.reset("theta2")
    assert data.statistics()["accumulators"]["theta2"]["n_entries"] == 0 and data.observations()
    data.reset()
    assert not data.observations() and len(data.rate_history()[0]) == 0
    assert len(changes) == 4


def test_dl3_file_and_page(tmp_path, subarray):
    path = tmp_path / "dl3.fits"
    hdu = fits.BinTableHDU(events_table(), name="EVENTS")
    hdu.header.update(HEADER)
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path)
    events, header = read_dl3(path)
    assert len(events) == 200 and header["OBJECT"] == "Mrk 421"

    store = ViewerStore(subarray)
    version = store.version
    make_feed(path, store).run()
    assert store.version > version
    session = Browser(store)
    page = next(p for p in session.pages if p.title == "DL3")
    page.refresh()
    assert page.observations_source.data["n_events"] == [200]
    assert page.observations_source.data["rate"] == ["2"]
    assert page.hist1d[0].captions["all"].text.startswith("All observations: N=200")
    assert page.hist2d[0].source.data["image"]
    page._reset()
    page.refresh()  # done at once by the session in a browser
    assert page.observations_source.data["n_events"] == []
