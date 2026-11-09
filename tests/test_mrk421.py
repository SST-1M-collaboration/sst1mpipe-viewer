"""
The viewer with the Mrk 421 test file of sst1mpipe (DL1 parameters in the camera frame, see
tests/data/README.md)
"""

from pathlib import Path

import numpy as np
import pytest
from bokeh.document import Document
from ctapipe.coordinates import TelescopeFrame
from ctapipe.image import hillas_parameters
from ctapipe.instrument import SubarrayDescription

from sst1mpipe_viewer.app import ViewerSession
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
    assert statistics["n_selected"] > 0
    assert statistics["accumulators"]["hillas_length"]["n_entries"] == statistics["n_selected"]
    assert statistics["accumulators"]["image_mask_fraction"]["n_entries"] == statistics["n_selected"]
    keys = store.event_keys(21)
    assert len(keys) == 1000

    session = ViewerSession(store, Document())
    assert session.tel_id == 21 and not session.follow
    assert session.event_key() == keys[0]
    session.step(+1)
    assert session.event_key() == keys[1]
    session.step(-5)
    assert session.event_key() == keys[0]

    # an event surviving the cleaning, by its event_id: its Hillas ellipse is drawn
    cleaned = [k for k in keys if np.isfinite(store.event(21, k)["dl1"]["hillas_intensity"])]
    session.go_to(str(cleaned[0][1]))
    assert session.event_key() == cleaned[0]
    dl1_page = session.pages[4]
    session.tabs.active = 4
    dl1_page.refresh()
    assert not dl1_page.message.visible
    assert dl1_page.image._ellipse_source.data["x"]

    # by index; the waveforms of the first 50 events are in the file
    session.go_to("#3")
    assert session.event_key() == keys[3]
    session.set_selected_pixels([100])
    for i, kind in ((1, "r0"), (2, "r1"), (3, "dl0")):
        page = session.pages[i]
        session.tabs.active = i
        page.refresh()
        assert not page.message.visible, kind
        assert page.waveforms.source.data["pixel"]
    # R0 of sst1mpipe: every field is readable
    r0 = session.pages[1]
    session.tabs.active = 1
    session.set_selected_pixels([10, 11])
    r0.refresh()
    assert list(r0.field_cameras) == ["pixel_flags"]  # one camera per pixel field (pedestal: its own)
    # the DigiCam baseline: camera and dashed lines on the waveforms (one per pixel)
    assert r0.baseline_camera.layout.visible
    assert len(r0.waveforms.baseline_source.data["ys"]) == 2
    # trigger traces per trigger patch (triplets of pixels)
    assert r0.trigger.layout.visible and r0.trigger.camera.n_pixels == 432
    assert len(r0.trigger.traces.source.data["pixel"]) >= 1  # patches of the selected pixels
    r0.trigger.trace.value = "trigger_output_patch7"
    r0.trigger.tapped(5, shift=False)
    assert len(session.selected_pixels) == 3
    # the table has all the fields of the R0, and those of the trigger
    names = set(r0.fields.source.data["name"])
    assert {"waveform", "pedestal", "pixel_flags", "trigger_input_traces", "_event_type"} <= names
    assert any(name.startswith("trigger.") for name in names)
    details = dict(zip(r0.fields.source.data["name"], r0.fields.source.data["details"]))
    assert details["waveform"] == "array (1, 1296, 50) int16"
    session.set_selected_pixels([])

    # unknown event: nothing changes, an error is shown
    session.go_to("123")
    assert session.event_key() == keys[3]
    assert "no event 123" in session.status.text or "no event 123" in session._status_text()

    # without waveforms (after the first 50 events)
    session.go_to("#100")
    session.pages[2].refresh()
    assert session.pages[2].message.visible


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
