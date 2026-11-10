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

    version = store.version
    store.reset_statistics(1, "hillas_length")
    assert store.statistics(1)["accumulators"]["hillas_length"]["n_entries"] == 0
    assert store.statistics(1)["accumulators"]["hillas_width"]["n_entries"] == 10
    store.reset_statistics()
    assert store.statistics(1)["n_rows"] == 0
    assert store.version > version


def test_dl2(subarray):
    """DL2 rows of ctapipe: statistics per combination of algorithms, with generic field names"""
    store = ViewerStore(subarray)
    rows = [dict(obs_id=1, event_id=i, tel_id=1, RF_tel_energy=10.0 ** (i - 2), RF_tel_energy_uncert=0.1,
                 RF_tel_is_valid=True, Classifier_tel_prediction=0.1 * i, Hillas_tel_alt=70.0, Hillas_tel_az=180.0,
                 Hillas_tel_impact_distance=100.0, Other_tel_energy=1.0) for i in range(1, 6)]
    store.push_table("dl2", Table(rows=rows))
    assert store.algorithms(1) == {"geometry": ["Hillas"], "energy": ["Other", "RF"], "classification": ["Classifier"],
                                   "impact": ["Hillas"]}
    snapshot = store.statistics(1, "dl2", {"energy": "RF"})
    assert snapshot["n_rows"] == 5
    assert snapshot["accumulators"]["prediction"]["n_entries"] == 5
    assert snapshot["accumulators"]["impact_distance"]["n_entries"] == 5
    assert snapshot["accumulators"]["energy"]["counts"].sum() == 5 and snapshot["accumulators"]["energy"]["std"] > 0
    other = store.statistics(1, "dl2")  # the first algorithm of each group
    assert other["accumulators"]["energy"]["std"] == 0 and other["accumulators"]["prediction"]["n_entries"] == 5
    assert store.statistics(1)["n_rows"] == 0  # the DL1 statistics are separate
    # event by event (buffered), and the DL2 of sst1mpipe shown as the algorithm "sst1mpipe"
    store.push_row("dl2", dict(obs_id=1, event_id=9, tel_id=2, reco_energy=1.0, gammaness=0.9))
    assert store.event(2, (1, 9))["dl2"]["sst1mpipe_tel_prediction"] == 0.9
    assert store.algorithms(2) == {"energy": ["sst1mpipe"], "classification": ["sst1mpipe"]}
    assert store.statistics(2, "dl2")["accumulators"]["energy"]["n_entries"] == 1
    store.reset_statistics(kind="dl2")
    assert store.statistics(1, "dl2")["n_rows"] == 0


def test_dl2_stereo(subarray):
    """The stereo DL2 are the events of the pseudo telescope SUBARRAY_ID"""
    from sst1mpipe_viewer.dl2 import SUBARRAY_ID

    store = ViewerStore(subarray)
    table = Table(dict(obs_id=[1, 1], event_id=[1, 2], Hillas_alt=[70.0, 71.0], Hillas_az=[10.0, 11.0],
                       Hillas_core_x=[5.0, -20.0], Hillas_core_y=[1.0, 2.0], Hillas_is_valid=[True, True],
                       Hillas_telescopes=[[True, True], [True, False]], RF_energy=[1.0, 2.0]))
    store.push_table("dl2_stereo", table)
    assert store.tel_ids == [1, 2] and store.event_tel_ids == [1, 2, SUBARRAY_ID]
    assert store.event_keys(SUBARRAY_ID) == [(1, 1), (1, 2)]
    assert store.algorithms(SUBARRAY_ID, "dl2_stereo") == {"geometry": ["Hillas"], "energy": ["RF"]}
    snapshot = store.statistics(SUBARRAY_ID, "dl2_stereo")
    assert snapshot["accumulators"]["core"]["counts"].sum() == 2
    assert snapshot["accumulators"]["energy"]["n_entries"] == 2
    store.push_row("dl2_stereo", dict(obs_id=1, event_id=3, Hillas_alt=72.0, Hillas_az=12.0))
    assert store.latest_key(SUBARRAY_ID, "dl2_stereo") == (1, 3)
    # a row without energy still fills the histograms of the geometry
    snapshot = store.statistics(SUBARRAY_ID, "dl2_stereo")
    assert snapshot["accumulators"]["alt"]["n_entries"] == 3 and snapshot["accumulators"]["energy"]["n_entries"] == 2


def test_dl2_containers(subarray):
    """push_event: the DL2 containers of ctapipe, per telescope and stereo"""
    import astropy.units as u
    from ctapipe.containers import (
        ArrayEventContainer,
        ParticleClassificationContainer,
        ReconstructedEnergyContainer,
        ReconstructedGeometryContainer,
        TelescopeImpactParameterContainer,
    )

    from sst1mpipe_viewer.dl2 import SUBARRAY_ID

    event = ArrayEventContainer()
    event.index.obs_id, event.index.event_id = 1, 5
    event.dl2.tel[1].energy["RF"] = ReconstructedEnergyContainer(energy=2 * u.TeV, is_valid=True)
    event.dl2.tel[1].particle_type["Classifier"] = ParticleClassificationContainer(prediction=0.7, is_valid=True)
    event.dl2.tel[1].impact["Hillas"] = TelescopeImpactParameterContainer(distance=120 * u.m)
    event.dl2.stereo.geometry["Hillas"] = ReconstructedGeometryContainer(
        alt=70 * u.deg, az=20 * u.deg, core_x=10 * u.m, core_y=-5 * u.m, is_valid=True, telescopes=[1, 2])
    store = ViewerStore(subarray)
    store.push_event(event)
    row = store.event(1, (1, 5))["dl2"]
    assert row["RF_tel_energy"] == 2.0 and row["Classifier_tel_prediction"] == 0.7
    assert row["Hillas_tel_impact_distance"] == 120.0
    assert store.algorithms(1) == {"energy": ["RF"], "classification": ["Classifier"], "impact": ["Hillas"]}
    stereo = store.event(SUBARRAY_ID, (1, 5))["dl2_stereo"]
    assert stereo["Hillas_core_x"] == 10.0 and list(stereo["Hillas_telescopes"]) == [1, 2]
    assert store.statistics(SUBARRAY_ID, "dl2_stereo")["accumulators"]["core"]["n_entries"] == 1


def test_rate_history(subarray):
    """Rate of the valid events per minute, from their timestamps, with Poisson errors"""
    store = ViewerStore(subarray)
    # the time of an event comes with its trigger row, before or after its other levels
    for event_id, event_time, intensity in ((0, 1000.0, 100.0), (1, 1005.0, np.nan), (2, 1010.0, 100.0)):
        store.push_row("dl1", dl1_row(event_id, intensity=intensity))
        store.push_row("trigger", dict(obs_id=1, event_id=event_id, tel_id=1, time=event_time))
    store.push_row("trigger", dict(obs_id=1, event_id=3, tel_id=1, time=1150.0))
    store.push_row("dl1", dl1_row(3))
    store.push_row("dl1", dl1_row(3))  # an event is counted once
    store.push_row("dl1", dl1_row(4))  # no timestamp: not in the rates
    times, rates, errors = store.rate_history(1, "dl1")
    # minutes 960-1020 (from the first valid event at 1000), 1020-1080, 1080-1140 (no event),
    # 1140-1200 (until the last event at 1150); the event 1 is not valid (no Hillas parameters)
    assert times.tolist() == [1010.0, 1050.0, 1110.0, 1145.0]
    assert np.allclose(rates, [2 / 20, 0, 0, 1 / 10]) and np.allclose(errors, [np.sqrt(2) / 20, 0, 0, 1 / 10])
    assert np.allclose(store.rate_history(1, "trigger")[1], [3 / 20, 0, 0, 1 / 10])
    assert store.latest_valid_key(1, "dl1") == (1, 4) and store.event_time(1, (1, 3)) == 1150.0

    # tables: the times of the valid events, from the table with a time column (here the trigger table)
    tables = ViewerStore(subarray)
    tables.push_table("dl1", Table(rows=[dl1_row(i, intensity=np.nan if i == 3 else 100.0) for i in range(5)]))
    assert len(tables.rate_history(1, "dl1")[0]) == 0  # no time yet
    tables.push_table("trigger", Table(dict(obs_id=[1] * 5, event_id=list(range(5)), tel_id=[1] * 5,
                                            time=[100.0, 110.0, 130.0, 140.0, 150.0])))
    times, rates, errors = tables.rate_history(1, "dl1")
    # minutes 60-120 (from the first event at 100) and 120-180 (until the last event at 150)
    assert times.tolist() == [110.0, 135.0]
    assert np.allclose(rates, [2 / 20, 2 / 30]) and np.allclose(errors, [np.sqrt(2) / 20, np.sqrt(2) / 30])
    assert tables.event_time(1, (1, 2)) == 130.0 and tables.event_time(1, (1, 99)) is None
    assert tables.latest_valid_key(1, "dl1") == (1, 4)


def test_validity():
    """A level of an event is valid if it has waveforms / Hillas parameters / a valid DL2 algorithm"""
    from sst1mpipe_viewer.validity import row_is_valid, valid_rows

    assert row_is_valid("r1", {"waveform": np.zeros((2, 3))}) and not row_is_valid("r1", {"pixel_status": 1})
    assert row_is_valid("dl1", {"hillas_intensity": 5.0}) and not row_is_valid("dl1", {"hillas_intensity": np.nan})
    assert row_is_valid("dl1", {"camera_frame_hillas_intensity": 5.0}) and not row_is_valid("dl1", {"image": 1})
    assert row_is_valid("dl2", {"A_tel_is_valid": False, "B_tel_is_valid": True})
    assert not row_is_valid("dl2", {"A_tel_is_valid": False}) and row_is_valid("dl2", {"A_tel_energy": 1.0})
    assert row_is_valid("trigger", {})
    assert valid_rows("dl1", {"hillas_intensity": np.array([1.0, np.nan])}).tolist() == [True, False]
    columns = {"A_is_valid": np.array([True, False, False]), "B_is_valid": np.array([False, False, True])}
    assert valid_rows("dl2_stereo", columns).tolist() == [True, False, True]
    assert valid_rows("r0", {"waveform": np.zeros((2, 1, 3))}).tolist() == [True, True]


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
    assert store.latest_valid_key(1, "dl1") == (1, 3)  # the last event has no Hillas parameters


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


def test_last_full_event_is_kept(subarray):
    """The last full event (with its waveforms or image) stays readable after max_events newer events"""
    store = ViewerStore(subarray, max_events=3)
    store.push_row("r1", r1_row(1))
    store.push_row("dl1", dl1_row(1))
    for i in range(2, 10):
        store.push_row("dl1", {k: v for k, v in dl1_row(i).items() if k not in ("image", "peak_time", "image_mask")})
    assert (1, 1) not in store.event_keys(1) and store.latest_display_key(1, "r1") == (1, 1)
    assert {"r1", "dl1"} <= set(store.event(1, (1, 1)))
