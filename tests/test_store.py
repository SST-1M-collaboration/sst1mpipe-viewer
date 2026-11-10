import threading

import numpy as np
import pytest
from astropy.table import Table
from conftest import N_PIXELS, dl1_row, r1_row

from sst1mpipe_viewer.store import ViewerStore


def test_rows_of_an_event_are_merged(subarray):
    store = ViewerStore(subarray)
    store.push_row("r1", r1_row(1))
    image = {k: v for k, v in dl1_row(1).items() if not k.startswith("hillas")}
    parameters = {k: v for k, v in dl1_row(1).items() if k.startswith("hillas") or k in ("obs_id", "event_id")}
    store.push_row("dl1", image)
    store.push_row("dl1", parameters, tel_id=1)
    event = store.event(1, (1, 1))
    assert set(event) == {"r1", "dl1"}
    assert "image" in event["dl1"] and "hillas_intensity" in event["dl1"]
    assert store.latest_key(1, "dl1") == (1, 1)
    assert store.counts()[(1, "dl1")] == 2


def test_statistics_and_reset(subarray):
    store = ViewerStore(subarray)
    table = Table(rows=[dl1_row(i, intensity=10.0 * i) for i in range(1, 11)])
    store.push_table("dl1", table)
    snapshot = store.statistics(1)
    assert snapshot["n_rows"] == 10
    # every row is accumulated (no cuts in the viewer)
    assert snapshot["accumulators"]["hillas_intensity"]["n_entries"] == 10
    assert snapshot["accumulators"]["hillas_length"]["n_entries"] == 10
    assert np.allclose(snapshot["accumulators"]["image_mask_fraction"]["values"][:5], 1)
    assert len(snapshot["accumulators"]["image_mask_fraction"]["values"]) == N_PIXELS

    version = store.version
    store.reset_statistics(1, "hillas_length")
    assert store.statistics(1)["accumulators"]["hillas_length"]["n_entries"] == 0
    assert store.statistics(1)["accumulators"]["hillas_width"]["n_entries"] == 10
    store.reset_statistics()
    assert store.statistics(1)["n_rows"] == 0
    assert store.version > version


def test_dl2(subarray):
    """DL2 rows: statistics of their own, ctapipe columns shown with the names of sst1mpipe"""
    store = ViewerStore(subarray)
    rows = [dict(obs_id=1, event_id=i, tel_id=1, reco_energy=10.0 ** (i - 2), gammaness=0.1 * i,
                 reco_alt=70.0, reco_az=180.0, reco_src_x=0.1, reco_src_y=-0.1) for i in range(1, 6)]
    store.push_table("dl2", Table(rows=rows))
    snapshot = store.statistics(1, "dl2")
    assert snapshot["n_rows"] == 5
    assert snapshot["accumulators"]["gammaness"]["n_entries"] == 5
    assert store.statistics(1)["n_rows"] == 0  # the DL1 statistics are separate
    # ctapipe DL2 (DataWriter names), pushed event by event
    store.push_row("dl2", dict(obs_id=1, event_id=9, tel_id=1, RandomForestRegressor_tel_energy=1.0,
                               RandomForestClassifier_tel_prediction=0.9))
    assert store.event(1, (1, 9))["dl2"]["gammaness"] == 0.9
    assert store.statistics(1, "dl2")["accumulators"]["reco_energy"]["n_entries"] == 6
    store.reset_statistics(kind="dl2")
    assert store.statistics(1, "dl2")["n_rows"] == 0


def test_rate_history(subarray, monkeypatch):
    """Rows per second, per minute with Poisson errors: by time of arrival (stream) or of the events (tables)"""
    import sst1mpipe_viewer.store as store_module

    now = [1000.0]
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    store = ViewerStore(subarray)
    for i in range(3):
        store.push_row("dl1", dl1_row(i))
    now[0] = 1150.0
    store.push_row("dl1", dl1_row(10))
    now[0] = 1160.0
    times, rates, errors = store.rate_history(1, "dl1")
    # minutes 960-1020 (covered from the first row at 1000), 1020-1080, 1080-1140 (no row), 1140-1200 (until now)
    assert times.tolist() == [1010.0, 1050.0, 1110.0, 1150.0]
    assert np.allclose(rates, [3 / 20, 0, 0, 1 / 20]) and np.allclose(errors, [np.sqrt(3) / 20, 0, 0, 1 / 20])

    # tables: the times of the events, from the table with a time column (here the trigger table)
    tables = ViewerStore(subarray)
    tables.push_table("dl1", Table(rows=[dl1_row(i) for i in range(4)]))
    assert len(tables.rate_history(1, "dl1")[0]) == 0  # no time yet
    tables.push_table("trigger", Table(dict(obs_id=[1] * 4, event_id=list(range(4)), tel_id=[1] * 4,
                                            time=[100.0, 110.0, 130.0, 150.0])))
    times, rates, errors = tables.rate_history(1, "dl1")
    # minutes 60-120 (from the first event at 100) and 120-180 (until the last event at 150)
    assert times.tolist() == [110.0, 135.0]
    assert np.allclose(rates, [2 / 20, 2 / 30]) and np.allclose(errors, [np.sqrt(2) / 20, np.sqrt(2) / 30])
    # time of an event, for the marker of the displayed event
    assert tables.event_time(1, (1, 2)) == 130.0 and tables.event_time(1, (1, 99)) is None
    store.push_row("trigger", dict(obs_id=1, event_id=10, tel_id=1, time=1234.5))
    assert store.event_time(1, (1, 10)) == 1234.5


def test_invalid_input(subarray):
    store = ViewerStore(subarray)
    with pytest.raises(ValueError, match="Unknown kind"):
        store.push_row("dl9", dl1_row(1))
    with pytest.raises(ValueError, match="Missing columns"):
        store.push_row("dl1", {"image": np.zeros(N_PIXELS)})


def test_max_events_and_navigation(subarray):
    store = ViewerStore(subarray, max_events=3)
    for i in range(5):
        store.push_row("dl1", dl1_row(i, intensity=np.nan if i == 4 else 100.0))
    assert store.event_keys(1) == [(1, 2), (1, 3), (1, 4)]
    assert store.find_latest_key(1, "dl1", "hillas_intensity") == (1, 3)


def test_push_from_threads(subarray):
    store = ViewerStore(subarray)

    def push(tel_id):
        for i in range(50):
            store.push_row("dl1", dl1_row(i, tel_id=tel_id))

    threads = [threading.Thread(target=push, args=(tel_id,)) for tel_id in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert store.statistics(1)["n_rows"] == 50 and store.statistics(2)["n_rows"] == 50


def test_updated_event_becomes_the_latest(subarray):
    store = ViewerStore(subarray)
    store.push_row("dl1", dl1_row(1))
    store.push_row("dl1", dl1_row(2))
    store.push_row("r1", r1_row(1))  # event 1 updated after event 2
    assert store.latest_key(1) == (1, 1)
    assert store.event_keys(1) == [(1, 2), (1, 1)]


def test_camera_maps_after_late_subarray(subarray):
    store = ViewerStore()
    parameters = {k: v for k, v in dl1_row(1).items() if k not in ("image", "peak_time", "image_mask")}
    store.push_row("dl1", parameters)
    store.set_subarray(subarray)
    store.push_row("dl1", dl1_row(2))
    assert store.statistics(1)["accumulators"]["image_mask_fraction"]["n_entries"] == 1


def test_tables_keep_all_their_events(subarray):
    """All the events of tables can be displayed (not only the last max_events), with all their kinds"""
    store = ViewerStore(subarray, max_events=3)
    store.push_table("dl1", Table(rows=[dl1_row(i) for i in range(10)]))
    store.push_table("r1", Table(rows=[r1_row(i) for i in range(10)]))
    assert store.event_keys(1) == [(1, i) for i in range(10)]
    assert all(set(store.event(1, key)) == {"dl1", "r1"} for key in store.event_keys(1))
    assert store.statistics(1)["n_rows"] == 10
    assert not store.has_event_data
    # events pushed one by one come after those of the tables
    store.push_row("dl1", dl1_row(20))
    assert store.event_keys(1)[-1] == (1, 20) and store.has_event_data


def test_rows_and_table_give_the_same_statistics(subarray):
    """The statistics filled event by event (buffered) and from a table are the same"""
    rows = [dl1_row(i, intensity=10.0 * i) for i in range(1, 40)]
    by_rows = ViewerStore(subarray, flush_size=7)  # several batches
    for row in rows:
        by_rows.push_row("dl1", row)
    by_table = ViewerStore(subarray)
    by_table.push_table("dl1", Table(rows=rows))
    a, b = by_rows.statistics(1), by_table.statistics(1)
    assert a["n_rows"] == b["n_rows"] == 39
    for name, snapshot in a["accumulators"].items():
        other = b["accumulators"][name]
        for key in ("counts", "values"):
            if key in snapshot:
                assert np.allclose(snapshot[key], other[key], equal_nan=True), name


def test_waveform_containers_are_converted_when_displayed(subarray):
    from ctapipe.containers import R1CameraContainer

    store = ViewerStore(subarray)
    container = R1CameraContainer(waveform=r1_row(1)["waveform"], pixel_status=np.full(N_PIXELS, 4))
    store.push_container("r1", container, obs_id=1, event_id=1, tel_id=1)
    assert store.counts()[(1, "r1")] == 1 and store.latest_key(1, "r1") == (1, 1)
    row = store.event(1, (1, 1))["r1"]
    assert row["waveform"].shape == (1, N_PIXELS, 20) and row["tel_id"] == 1
    # a second row of the same event is merged with it
    store.push_row("r1", {"obs_id": 1, "event_id": 1, "tel_id": 1, "extra": 3.0})
    assert {"waveform", "extra"} <= set(store.event(1, (1, 1))["r1"])


def test_rates_stay_small(subarray):
    """The arrivals of the rates are merged and pruned when pushing, without reading the rates"""
    store = ViewerStore(subarray)
    for i in range(500):
        store.push_row("trigger", {"obs_id": 1, "event_id": i, "tel_id": 1, "event_type": 32})
    assert len(store._arrivals[(1, "trigger")]) <= 2
    assert store.rates()[(1, "trigger")] == 500 / 10.0
