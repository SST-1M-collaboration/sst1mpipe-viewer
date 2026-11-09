"""Selection of the pixels by groups of DigiCam (trigger patches, modules, FADC boards, sectors)"""

from pathlib import Path

import numpy as np
import pytest
from conftest import Browser
from ctapipe.instrument import SubarrayDescription
from scipy.sparse.csgraph import connected_components

from sst1mpipe_viewer.components import WaveformPanel
from sst1mpipe_viewer.pixel_groups import GROUPINGS, parse_ids, pixel_groups
from sst1mpipe_viewer.store import ViewerStore

MRK421_FILE = Path(__file__).parent / "data" / "mrk421_tel21_tel22.h5"
needs_file = pytest.mark.skipif(
    not MRK421_FILE.is_file() or MRK421_FILE.stat().st_size < 1000, reason="git lfs pull"
)


def test_parse_ids():
    assert parse_ids("3, 5-7 12; 20 - 22") == [3, 5, 6, 7, 12, 20, 21, 22]
    assert parse_ids(" ") == []
    with pytest.raises(ValueError):
        parse_ids("3, x")


def test_groups_of_digicam():
    groups = pixel_groups()
    assert groups.n_pixels == 1296
    sizes = {"patch": 3, "module": 12, "fadc_board": 48, "can_node": 36, "sector": 432}
    for column, size in sizes.items():
        _, counts = np.unique(groups.ids[column], return_counts=True)
        assert set(counts) == {size}, column
    assert set(GROUPINGS.values()) == set(groups.ids)


@pytest.fixture(scope="module")
def digicam():
    return SubarrayDescription.from_hdf(MRK421_FILE)


@needs_file
@pytest.mark.parametrize("column", ["patch", "module", "sector"])
def test_groups_are_contiguous_in_the_camera_of_the_data(digicam, column):
    """The pixels of a group are neighbours in the geometry of the data: the pixel order is the same"""
    geometry = digicam.tel[21].camera.geometry
    groups = pixel_groups()
    assert groups.matches(geometry)
    values = groups.values(geometry, column)
    neighbors = geometry.neighbor_matrix_sparse
    for group in np.unique(values)[:50]:
        pixels = np.flatnonzero(values == group)
        n_components, _ = connected_components(neighbors[pixels][:, pixels], directed=False)
        assert n_components == 1, (column, group)


@needs_file
def test_selection_by_group(digicam):
    store = ViewerStore(digicam)
    session = Browser(store)
    session.pages[0].refresh()
    tel_id = session.tel_ids[0]
    # one pixel selection per telescope
    panel = session.pages[0].pixel_selections[tel_id]
    assert panel.camera.layout.visible

    # a click selects the module of the pixel, shift+click adds / removes a module
    panel.grouping.value = "Module"
    panel.tapped(0, shift=False)
    first = list(session.selected_pixels(tel_id))
    assert len(first) == 12 and 0 in first
    other = next(p for p in range(1296) if p not in first)
    panel.tapped(other, shift=True)
    assert len(session.selected_pixels(tel_id)) == 24
    panel.tapped(0, shift=True)
    assert len(session.selected_pixels(tel_id)) == 12 and 0 not in session.selected_pixels(tel_id)

    # ids of sectors
    panel.grouping.value = "Sector"
    panel.select_ids("1-2")
    assert len(session.selected_pixels(tel_id)) == 864
    panel.select_ids("3", add=True)
    assert len(session.selected_pixels(tel_id)) == 1296
    panel.select_ids("9")
    assert "Unknown sector ids: [9]" in panel.message.text
    assert len(session.selected_pixels(tel_id)) == 1296  # unknown ids only: selection kept
    session.pages[0].refresh()
    assert "1296 pixels selected" in panel.info.text and "complete sectors: 1, 2, 3" in panel.info.text
    panel.select_ids("2")
    session.pages[0].refresh()
    assert "432 pixels selected" in panel.info.text and "complete sectors: 2<" not in panel.info.text
    assert panel.info.text.endswith("complete sectors: 2")


def test_not_digicam(subarray):
    """Other cameras: the group selection is not available"""
    session = Browser(ViewerStore(subarray))
    session.pages[0].refresh()
    panel = session.pages[0].pixel_selections[1]
    assert not panel.camera.layout.visible and "not available" in panel.message.text
    panel.tapped(0, shift=False)
    assert session.selected_pixels(1) == []


def test_mean_waveform_of_many_pixels():
    panel = WaveformPanel()
    waveforms = np.arange(40.0).reshape(20, 2)
    panel.set_waveforms(waveforms, list(range(20)))
    assert panel.source.data["pixel"] == ["mean of 20 pixels"]
    assert np.allclose(panel.source.data["ys"][0], waveforms.mean(axis=0))
    panel.set_waveforms(waveforms, [1, 2])
    assert panel.source.data["pixel"] == ["1", "2"]


@needs_file
def test_array_on_a_map(digicam):
    """The telescopes are shown at their Earth location on OpenStreetMap (Ondrejov)"""
    from sst1mpipe_viewer.components.array import earth_locations, web_mercator

    lon, lat, height = earth_locations(digicam)
    assert np.allclose(lat, 49.912, atol=0.002) and np.allclose(lon, 14.782, atol=0.002)
    x, y = web_mercator([0.0, 180.0], [0.0, 0.0])
    assert np.allclose(x, [0, 20037508.34], atol=1) and np.allclose(y, 0)

    session = Browser(ViewerStore(digicam))
    array_page = session.pages[0]
    array_page.refresh()
    assert list(array_page.array_panels) == ["Map (OpenStreetMap)", "Ground frame"]
    map_panel = array_page.array_panels["Map (OpenStreetMap)"]
    assert map_panel.layout.visible and not array_page.array_panels["Ground frame"].layout.visible
    # a click on a telescope selects or unselects it; the telescopes have their colors
    assert session.tel_ids == [21, 22]
    map_panel._clicked("indices", [], [1])
    assert session.tel_ids == [21]
    array_page.refresh()
    assert array_page.telescopes.active == [0]
    assert len(map_panel._ring.data["x"]) == 1
    map_panel._clicked("indices", [], [1])
    assert session.tel_ids == [21, 22]
    colors = map_panel.source.data["color"]
    assert colors[0] != colors[1] and colors[0] == session.color(21)
    # the selection with the boxes
    array_page.telescopes.active = [1]
    assert session.tel_ids == [22]
