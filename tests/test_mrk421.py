"""
The viewer with the Mrk 421 test file of sst1mpipe (DL1 parameters in the camera frame, see
tests/data/README.md)
"""

from pathlib import Path

import numpy as np
import pytest
from conftest import Browser
from ctapipe.coordinates import TelescopeFrame
from ctapipe.image import hillas_parameters
from ctapipe.instrument import SubarrayDescription

from sst1mpipe_viewer.feeds import HDF5Feed, read_tables
from sst1mpipe_viewer.store import ViewerStore

MRK421_FILE = Path(__file__).parent / "data" / "mrk421_tel21_tel22.h5"

pytestmark = pytest.mark.skipif(
    not MRK421_FILE.is_file() or MRK421_FILE.stat().st_size < 1000,
    reason="Mrk 421 test file not available (git lfs pull)",
)


@pytest.fixture(scope="module")
def subarray():
    return SubarrayDescription.from_hdf(MRK421_FILE)


@pytest.fixture(scope="module")
def tables():
    return read_tables(MRK421_FILE)


def test_file_content(subarray, tables):
    assert subarray.tel_ids.tolist() == [21, 22]
    assert len(tables[("dl1", 21)]) == 1000 and len(tables[("dl1", 22)]) == 22
    assert "camera_frame_hillas_intensity" in tables[("dl1", 21)].colnames


@pytest.mark.parametrize("tel_id", [21, 22])
def test_telescope_frame_parameters(subarray, tables, tel_id):
    """The parameters converted from the camera frame are those computed by ctapipe in the telescope frame"""
    store = ViewerStore(subarray)
    store.push_table("dl1", tables[("dl1", tel_id)])
    geometry = subarray.tel[tel_id].camera.geometry.transform_to(TelescopeFrame())
    n_checked = 0
    for key in store.event_keys(tel_id):
        row = store.event(tel_id, key)["dl1"]
        if not np.isfinite(row["hillas_intensity"]) or row["image_mask"].sum() < 3:
            continue
        image = np.where(row["image_mask"], row["image"], 0.0)
        hillas = hillas_parameters(geometry, image)
        assert np.isclose(row["hillas_intensity"], hillas.intensity, rtol=1e-4)
        assert np.isclose(row["hillas_fov_lon"], hillas.fov_lon.to_value("deg"), atol=1e-3)
        assert np.isclose(row["hillas_fov_lat"], hillas.fov_lat.to_value("deg"), atol=1e-3)
        assert np.isclose(row["hillas_length"], hillas.length.to_value("deg"), rtol=1e-2)
        assert np.isclose(row["hillas_width"], hillas.width.to_value("deg"), rtol=1e-2, atol=1e-4)
        # psi is defined modulo 180 deg
        dpsi = (row["hillas_psi"] - hillas.psi.to_value("deg") + 90) % 180 - 90
        assert abs(dpsi) < 0.5
        assert np.isclose(row["hillas_skewness"], hillas.skewness, rtol=1e-2, atol=1e-3)
        n_checked += 1
    assert n_checked >= (5 if tel_id == 21 else 1)


def test_file_mode(subarray):
    """
    A file is processed at once: statistics of all its DL1 events, the first event shown, every
    event reachable with Prev / Next and by its event_id or index, all the data levels shown
    """
    store = ViewerStore()
    HDF5Feed(MRK421_FILE, store).run()
    statistics = store.statistics(21)
    assert statistics["n_rows"] == 1000
    assert statistics["accumulators"]["hillas_length"]["n_entries"] == 1000
    # rates in time of the events (trigger times of the file)
    times, rates, errors = store.rate_history(21, "dl1")
    # only the events with a valid DL1 (Hillas parameters) are counted
    assert len(times) >= 1 and 5 < rates.max() < 100 and np.all(errors < rates)
    assert store.latest_valid_key(21, "dl1") != store.latest_key(21, "dl1")
    keys = store.event_keys(21)
    assert len(keys) == 1000

    session = Browser(store)
    assert session.tel_ids == [21, 22] and not session.follow
    assert session.event_key(21) == keys[0]
    session.set_tels([21])
    session.step(+1)
    assert session.event_key(21) == keys[1]
    session.step(-5)
    assert session.event_key(21) == keys[0]

    # an event surviving the cleaning, by its event_id: its Hillas ellipse is drawn
    cleaned = [k for k in keys if np.isfinite(store.event(21, k)["dl1"]["hillas_intensity"])]
    session.go_to(str(cleaned[0][1]))
    assert session.event_key(21) == cleaned[0]
    dl1_page = session.pages[4]
    dl1_page.refresh()
    assert not dl1_page.views[21].message.text
    assert dl1_page.views[21].camera._ellipse_source.data["x"]

    # by index; the waveforms of the first 50 events are in the file
    session.go_to("#3")
    assert session.event_key(21) == keys[3]
    session.set_selected_pixels([100], 21)
    for i, kind in ((1, "r0"), (2, "r1"), (3, "dl0")):
        page = session.pages[i]
        page.refresh()
        assert not page.views[21].message.text, kind
        assert page.views[21].waveforms.source.data["pixel"]
    # R0 of sst1mpipe: every field is readable, the fields of the same shape in a menu
    r0 = session.pages[1]
    session.set_selected_pixels([10, 11], 21)
    r0.refresh()
    assert {"pedestal", "pixel_flags"} <= set(r0.pixel_field.options)
    assert r0.waveform_field.options == ["waveform"]
    view = r0.views[21]
    # the DigiCam baseline: dashed lines on the waveforms (one per pixel), and in the pixel field menu
    assert len(view.waveforms.baseline_source.data["ys"]) == 2
    r0.pixel_field.value = "pedestal"
    assert view.field_camera.figure.title.text == "pedestal"
    # trigger traces per trigger patch (triplets of pixels), chosen in a menu
    assert view.trigger.camera.n_pixels == 432
    assert len(view.trigger.traces.source.data["pixel"]) >= 1  # patches of the selected pixels
    assert "trigger_output_patch7" in r0.trace.options
    r0.trace.value = "trigger_output_patch7"
    # one sample per telescope, common to the waveforms and the trigger traces
    view.sample.value = 7
    r0.refresh()
    assert view.camera.figure.title.text == "waveform sample 7"
    assert view.trigger.camera.figure.title.text == "trigger_output_patch7 sample 7"
    view.trigger.tapped(5, shift=False)
    assert len(session.selected_pixels(21)) == 3
    # the table has all the fields of the R0, and those of the trigger
    data = r0.fields.source.data
    names = set(data["name"])
    assert {"waveform", "pedestal", "pixel_flags", "trigger_input_traces", "_event_type"} <= names
    assert any(name.startswith("trigger.") for name in names)
    assert dict(zip(data["name"], data["tel_21"]))["waveform"] == "array (1, 1296, 50) int16"
    session.set_selected_pixels([], 21)

    # unknown event: nothing changes, an error is shown
    session.go_to("123")
    assert session.event_key(21) == keys[3]
    assert "no event 123" in session._status_text()

    # without waveforms (after the first 50 events)
    session.go_to("#100")
    session.pages[2].refresh()
    assert session.pages[2].views[21].message.text

    # both telescopes: one block each, one column each in the table
    session.set_tels([21, 22])
    session.go_to("#0")
    r1 = session.pages[2]
    r1.refresh()
    assert [child for child in r1.views_container.children] == [r1.views[21].layout, r1.views[22].layout]
    assert not r1.views[21].message.text and not r1.views[22].message.text
    assert {"tel_21", "tel_22"} <= set(r1.fields.source.data)


def test_files_of_one_telescope_each(tmp_path, subarray):
    """Files of one telescope each (as written by sst1mpipe): the telescopes of all of them are shown"""
    from ctapipe.io import write_table

    paths = []
    for tel_id in (21, 22):
        path = tmp_path / f"tel{tel_id}.h5"
        subarray.select_subarray([tel_id]).to_hdf(path)
        tables = read_tables(MRK421_FILE, tel_ids=[tel_id])
        write_table(tables[("dl1", tel_id)][:5], path, f"/dl1/event/telescope/parameters/tel_{tel_id:03d}")
        paths.append(path)
    store = ViewerStore()
    for path in paths:
        HDF5Feed(path, store).run()
    assert store.subarray.tel_ids.tolist() == [21, 22]
    assert store.statistics(22)["n_rows"] == 5


def test_replay_rate(subarray):
    """The events of a file replayed at a rate are pushed one by one at this rate"""
    import time

    store = ViewerStore(subarray)
    feed = HDF5Feed(MRK421_FILE, store, rate=500, loop=True).start()
    time.sleep(1.0)
    _ = feed.tables  # read before the timing
    start, n_start = time.monotonic(), sum(n for (_, kind), n in store.counts().items() if kind == "dl1")
    time.sleep(2.0)
    n = sum(n for (_, kind), n in store.counts().items() if kind == "dl1") - n_start
    rate = n / (time.monotonic() - start)
    feed.stop()
    assert store.has_event_data
    # not faster than asked; slower only if the machine is very busy
    assert 100 < rate < 550, rate
