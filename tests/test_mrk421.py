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
from sst1mpipe_viewer.demo import DemoFeed, read_tables
from sst1mpipe_viewer.store import ViewerStore

MRK421_FILE = Path(__file__).parent / "data" / "mrk421_tel21_tel22.dl1.h5"

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


def test_viewer_pages(subarray):
    """All the pages are shown with the file, the statistics are filled"""
    store = ViewerStore()
    DemoFeed(MRK421_FILE, store, rate=0).run()
    session = ViewerSession(store, Document())
    assert session.tel_id == 21
    for i, page in enumerate(session.pages):
        session.tabs.active = i
        page.refresh()
    statistics = store.statistics(21)
    assert statistics["n_rows"] == 1000
    assert statistics["n_selected"] > 0
    assert statistics["accumulators"]["hillas_length"]["n_entries"] == statistics["n_selected"]
    assert statistics["accumulators"]["image_mask_fraction"]["n_entries"] == statistics["n_selected"]
    dl1_page = session.pages[4]
    assert not dl1_page.message.visible
    assert dl1_page.image._ellipse_source.data["x"]  # Hillas ellipse drawn
