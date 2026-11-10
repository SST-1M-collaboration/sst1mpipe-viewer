"""The pages are built and refreshed without browser"""

import numpy as np
from astropy.table import Table
from bokeh.document import Document
from bokeh.events import Tap
from conftest import Browser, dl1_row, r1_row

from sst1mpipe_viewer.components import CameraPanel, Histogram1DPanel
from sst1mpipe_viewer.pages.waveforms import sample_image
from sst1mpipe_viewer.store import ViewerStore


def make_session(subarray):
    store = ViewerStore(subarray)
    for i in range(3):
        store.push_row("r1", r1_row(i))
        store.push_row("dl1", dl1_row(i))
    store.push_row("dl1", dl1_row(10, tel_id=2))
    return store, Browser(store)


def refresh_all(session):
    for page in session.pages:
        page.refresh()


def test_all_pages_refresh(subarray):
    store, session = make_session(subarray)
    assert session.tel_ids == [1, 2]  # all the telescopes are selected at first
    assert [p.title for p in session.pages] == ["Array", "R0", "R1", "DL0", "DL1 Event", "DL1 Statistics",
                                                "DL2 Event", "DL2 Statistics", "DL2 Stereo", "DL3"]
    refresh_all(session)
    r0, r1 = session.pages[1], session.pages[2]
    # one block per selected telescope
    assert [view.tel_id for view in r1.views.values()] == [1, 2]
    assert r0.views[1].message.text  # no R0 data
    assert not r1.views[1].message.text and r1.views[2].message.text  # R1 of TEL 1 only
    # without selection no waveform is shown (no computation to choose a pixel)
    assert r1.views[1].waveforms.source.data["pixel"] == []
    # all the fields of the events are in the table, one column per telescope
    assert {"waveform", "pixel_status", "event_id"} <= set(r1.fields.source.data["name"])
    # the per pixel fields are chosen in a menu
    assert r1.pixel_field.options == ["pixel_status"]
    assert session.pages[4].fields.source.data["name"]


def test_selection_navigation_telescopes(subarray):
    store, session = make_session(subarray)
    session.set_selected_pixels([3, 4], 1)
    session.pages[2].refresh()
    assert session.pages[2].views[1].waveforms.source.data["pixel"] == ["3", "4"]
    # each telescope has its own pixel selection
    assert session.selected_pixels(2) == []
    session.set_selected_pixels([5], 2)
    assert session.selected_pixels(1) == [3, 4] and session.selected_pixels(2) == [5]
    session.clear_selected_pixels()
    assert session.selected_pixels(1) == [] and session.selected_pixels(2) == []
    session.set_selected_pixels([3, 4], 1)

    # each telescope has its displayed event
    session.step(-1)
    assert not session.follow and session.event_key(1) == (1, 1) and session.event_key(2) == (1, 10)
    # Prev / Next of one telescope: the other telescope keeps its event
    session.step(+1, [1])
    assert session.event_key(1) == (1, 2) and session.event_key(2) == (1, 10)
    session.step(-1, [1])
    assert session.event_key(1) == (1, 1)
    session.step(-5)
    assert session.event_key(1) == (1, 0)
    session.set_follow(True)
    assert session.event_key(1, "dl1") == (1, 2)

    # telescopes selected in the Array page: the pages show the selected ones
    session.set_tels([2])
    assert session.tel_ids == [2]
    refresh_all(session)
    assert list(session.pages[2].views_container.children) == [session.pages[2].views[2].layout]
    counters = session.pages[5].counters_source.data
    assert counters["tel"] == ["TEL 2"] and counters["rows"] == [1]
    session.toggle_tel(1)
    assert session.tel_ids == [1, 2]
    refresh_all(session)
    assert session.pages[5].counters_source.data["tel"] == ["TEL 1", "TEL 2"]
    # the statistics: one color per telescope
    histogram = session.pages[5].hist1d[0]
    assert histogram.renderers[1].glyph.fill_color != histogram.renderers[2].glyph.fill_color


def test_without_subarray():
    store = ViewerStore()
    store.push_row("dl1", dl1_row(1))
    session = Browser(store)
    refresh_all(session)
    assert "geometry" in session.pages[4].views[1].message.text


def test_tick_refreshes_only_on_change(subarray):
    store, session = make_session(subarray)
    calls = []
    page = session.page
    page.refresh = lambda: calls.append(1)
    # the session was refreshed when created: nothing changed since
    session.tick()
    assert len(calls) == 0
    store.push_row("dl1", dl1_row(20))
    session.tick()
    session.tick()
    assert len(calls) == 1
    session.set_selected_pixels([1], 1)
    session.tick()
    assert len(calls) == 2


def test_components(subarray):
    geometry = subarray.tel[1].camera.geometry
    panel = CameraPanel(geometry)
    panel.set_image(np.arange(geometry.n_pixels, dtype=float))
    assert panel.display.norm.high == geometry.n_pixels - 1
    # the color scale is set when the viewer starts
    panel = CameraPanel(geometry, scale="log")
    panel.set_image(np.arange(geometry.n_pixels, dtype=float))
    assert panel.display.norm.low == 1
    panel.set_ellipse({"hillas_fov_lon": 0, "hillas_fov_lat": 0, "hillas_length": 1, "hillas_width": 0.5,
                       "hillas_psi": 90})
    assert panel._ellipse_source.data["width"] == [2]
    panel.set_ellipse({"hillas_fov_lon": np.nan})
    assert panel._ellipse_source.data["x"] == []

    clicked = []
    panel = CameraPanel(geometry, on_pixel_click=clicked.append)
    x, y = geometry.pix_x.to_value("m"), geometry.pix_y.to_value("m")
    panel._tapped(Tap(panel.figure, x=x[3], y=y[3]))
    panel._tapped(Tap(panel.figure, x=x[5], y=y[5], modifiers={"shift": True, "ctrl": False, "alt": False}))
    panel._tapped(Tap(panel.figure, x=100.0, y=100.0))  # outside of the camera: ignored
    assert clicked == [[3], [3, 5]]
    panel._tapped(Tap(panel.figure, x=x[3], y=y[3], modifiers={"shift": True, "ctrl": False, "alt": False}))
    assert clicked[-1] == [5]

    histogram = Histogram1DPanel("x", log_y=True, colors={1: "red", 2: "blue"})
    histogram.update({1: dict(edges=np.arange(4.0), counts=np.array([0, 2, 1]), n_entries=3, underflow=0,
                              overflow=0, n_invalid=0, mean=1.0, std=0.5)})
    assert np.isnan(histogram.sources[1].data["top"][0])  # empty bin not drawn
    assert histogram.captions[1].text.startswith("TEL 1: N=3") and histogram.captions[2].text == ""
    assert histogram.figure.x_range.end == 3
    assert histogram.renderers[1].visible and not histogram.renderers[2].visible

    waveforms = np.arange(6.0).reshape(2, 3)
    assert list(sample_image(waveforms, 1)) == [1, 4]
    assert list(sample_image(waveforms, 10)) == [2, 5]  # the last sample


def test_server_pages(subarray):
    """One page (bokeh application) per data level"""
    from sst1mpipe_viewer.server import make_server

    store = ViewerStore(subarray)
    server = make_server(store, port=0, refresh_period=2000)
    try:
        assert set(server._tornado.applications) == {"/", "/r0", "/r1", "/dl0", "/dl1", "/dl1_statistics", "/dl2",
                                                       "/dl2_statistics", "/dl2_stereo", "/dl3"}
        for path, title in (("/", "Array"), ("/r1", "R1"), ("/dl1_statistics", "DL1 Statistics"),
                            ("/dl2_statistics", "DL2 Statistics")):
            doc = Document()
            server._tornado.applications[path].application.initialize_document(doc)
            assert doc.title == f"SST-1M Event Viewer – {title}"
            assert len(doc.session_callbacks) == 1
    finally:
        server.stop()


def test_pages_of_a_browser_share_their_state(subarray):
    """A change in a page (pixels, event, telescope) is followed by the other pages of the browser"""
    from types import SimpleNamespace

    from sst1mpipe_viewer.app import StateRegistry, ViewerSession, _client_id

    store, browser = make_session(subarray)
    array, r1 = browser.sessions[0], browser.sessions[2]
    array.set_selected_pixels([3, 4], 1)
    array.step(-1)
    r1.tick()
    assert r1.page.views[1].waveforms.source.data["pixel"] == ["3", "4"]
    assert not r1.live.active and r1.live.button_type == "default"
    array.set_tels([2])
    r1.tick()
    assert list(r1.page.views_container.children) == [r1.page.views[2].layout]

    # the pages of the same client id (in their URL) share a state, other clients have their own
    registry = StateRegistry()

    def doc_of(url_arguments):
        return SimpleNamespace(session_context=SimpleNamespace(request=SimpleNamespace(arguments=url_arguments)))

    assert _client_id(doc_of({"c": [b"abc"]})) == "abc"
    assert _client_id(doc_of({})) is None
    assert _client_id(doc_of({"c": [b"<script>"]})) is None  # only alphanumeric ids
    assert _client_id(Document()) is None
    assert registry.get("abc", store) is registry.get("abc", store)
    assert registry.get("abc", store) is not registry.get("xyz", store)
    session = ViewerSession(store, Document(), page="r0", state=registry.get("abc", store), client_id="abc")
    assert "/r1?c=abc" in session.layout.children[1].text


def test_same_camera_is_not_redrawn(subarray):
    """Changing to a telescope with the same camera keeps the drawing of the pixels"""
    from sst1mpipe_viewer.app import ViewerSession

    store, _ = make_session(subarray)
    session = ViewerSession(store, Document(), page="r1")
    camera = session.page.views[1].camera
    renderer = camera.display._patches
    camera.set_geometry(session.geometry(2))
    assert camera.display._patches is renderer and camera.geometry is session.geometry(2)
    # the selection and the cleaning mask are layers of their pixels only
    camera.set_selected([1, 2])
    assert len(camera._selected_source.data["xs"]) == 2
    camera.set_mask(np.arange(camera.n_pixels) < 5)
    assert len(camera._mask_source.data["xs"]) == 5


def test_file_loaded_after_the_session(subarray):
    """A session opened before a file is loaded goes to its first event"""
    from astropy.table import Table

    store = ViewerStore(subarray)
    session = Browser(store)
    assert session.follow
    store.push_table("dl1", Table(rows=[dl1_row(i) for i in range(5)]))
    session.tick()
    assert not session.follow and session.event_key(1) == (1, 0)
    session.go_to("#-1")
    assert session.event_key(1) == (1, 4)
    session.go_to("not a number")
    session.tick()
    assert session.event_key(1) == (1, 4) and "no event" in session.status.text


def test_stream_keeps_following(subarray):
    """Events pushed one by one: the session follows the last one"""
    store = ViewerStore(subarray)
    session = Browser(store)
    store.push_row("dl1", dl1_row(1))
    session.tick()
    assert session.follow and session.event_key(1, "dl1") == (1, 1)


def test_dl2_pages(subarray):
    """DL2 Event: all the DL2 fields; DL2 Statistics: the algorithm of each group chosen in a menu"""
    store = ViewerStore(subarray)
    store.push_row("dl1", dl1_row(1))
    store.push_row("dl2", dict(obs_id=1, event_id=1, tel_id=1, RF_tel_energy=1.0, Other_tel_energy=100.0,
                               Classifier_tel_prediction=0.8, Hillas_tel_alt=70.0, Hillas_tel_az=10.0))
    session = Browser(store)
    refresh_all(session)
    page = session.pages[6]
    assert "RF_tel_energy" in page.fields.source.data["name"]
    statistics = session.pages[7]
    assert statistics.counters_source.data["rows"] == [1, 0]
    assert statistics.algorithm_selects["energy"].options == ["Other", "RF"]
    assert not statistics.algorithm_selects["disp"].visible
    energy = statistics.hist1d[0]
    assert energy.captions[1].text.startswith("TEL 1: N=1 mean=100 ")
    assert energy.figure.x_scale.__class__.__name__ == "LogScale"  # logarithmic bins on a logarithmic axis
    statistics.algorithm_selects["energy"].value = "RF"
    statistics.refresh()
    assert energy.captions[1].text.startswith("TEL 1: N=1 mean=1 ")


def test_dl2_stereo_page(subarray):
    """DL2 Stereo: the displayed stereo event (core, fields), browsed with the telescopes, and its statistics"""
    store = ViewerStore(subarray)
    store.push_table("dl1", Table(rows=[dl1_row(i) for i in (1, 2)]))
    store.push_table("dl2_stereo", Table(dict(
        obs_id=[1, 1], event_id=[1, 2], Hillas_alt=[70.0, 71.0], Hillas_az=[10.0, 11.0], Hillas_core_x=[5.0, -20.0],
        Hillas_core_y=[1.0, 2.0], Hillas_telescopes=[[True, True], [True, False]], RF_energy=[1.0, 2.0])))
    session = Browser(store)
    refresh_all(session)
    page = next(p for p in session.pages if p.title == "DL2 Stereo")
    assert page.core_source.data == dict(x=[5.0], y=[1.0])
    assert "telescopes 1, 2" in page.summary.text and "Hillas_core_x" in page.fields.source.data["name"]
    assert page.statistics.counters_source.data == dict(tel=["Subarray"], rows=[2])
    session.step(+1)  # Next moves the telescopes and the subarray
    page.refresh()
    assert page.core_source.data == dict(x=[-20.0], y=[2.0]) and "telescopes 1" in page.summary.text
    assert list(page.telescopes_source.data["line"]).count("white") == 1


def test_rate_panel():
    """Rates with error bars, markers of the displayed events"""
    from sst1mpipe_viewer.components import RatePanel

    panel = RatePanel("rates", {"a": ("A", "red")}, markers={"a": "red"})
    panel.update({"a": (np.array([1.0, 2.0]), np.array([5.0, 6.0]), np.array([1.0, 7.0]))})
    source = panel.sources["a"]
    assert list(source.data["time"]) == [1000.0, 2000.0]
    assert list(source.data["lower"]) == [4.0, 0.0] and list(source.data["upper"]) == [6.0, 13.0]
    panel.set_markers({"a": 1.5})
    assert panel.markers["a"].data["x"] == [1500.0]
    panel.set_markers({})
    assert panel.markers["a"].data["x"] == []
    panel.update({}, visible=[])
    assert not any(r.visible for r in panel.renderers["a"])


def test_displayed_event_marker(subarray):
    """The rate plot of a level has a vertical line at the time of the displayed event of each telescope"""
    store = ViewerStore(subarray)
    store.push_table("dl1", Table(rows=[dl1_row(i) for i in range(3)]))
    store.push_table("trigger", Table(dict(obs_id=[1] * 3, event_id=[0, 1, 2], tel_id=[1] * 3,
                                           time=[100.0, 130.0, 150.0])))
    session = Browser(store)
    refresh_all(session)
    page = session.pages[4]
    assert page.rates.panel.markers[1].data["x"] == [100e3]
    session.step(+1, [1])
    page.refresh()
    assert page.rates.panel.markers[1].data["x"] == [130e3] and page.rates.panel.markers[2].data["x"] == []
