"""The pages are built and refreshed without browser"""

import numpy as np
from bokeh.document import Document
from bokeh.events import Tap
from conftest import dl1_row, r1_row

from sst1mpipe_viewer.app import ViewerSession
from sst1mpipe_viewer.components import CameraPanel, Histogram1DPanel
from sst1mpipe_viewer.pages.waveforms import camera_quantity
from sst1mpipe_viewer.store import ViewerStore


def make_session(subarray):
    store = ViewerStore(subarray)
    for i in range(3):
        store.push_row("r1", r1_row(i))
        store.push_row("dl1", dl1_row(i))
    store.push_row("dl1", dl1_row(10, tel_id=2))
    return store, ViewerSession(store, Document())


def refresh_all(session):
    for i, page in enumerate(session.pages):
        session.tabs.active = i
        page.refresh()


def test_all_pages_refresh(subarray):
    store, session = make_session(subarray)
    assert session.tel_id == 1
    assert [p.title for p in session.pages] == ["Overview", "R0", "R1", "DL0", "DL1 Event", "DL1 Statistics"]
    refresh_all(session)
    r0, r1 = session.pages[1], session.pages[2]
    assert r0.message.visible  # no R0 data
    assert not r1.message.visible
    # the brightest pixel is shown without selection
    assert r1.waveforms.source.data["pixel"] == ["7"]
    assert session.pages[4].parameters.source.data["name"]


def test_selection_navigation_telescope(subarray):
    store, session = make_session(subarray)
    session.set_selected_pixels([3, 4])
    session.pages[2].refresh()
    assert session.pages[2].waveforms.source.data["pixel"] == ["3", "4"]

    session.step(-1)
    assert not session.follow and session.event_key() == (1, 1)
    session.step(-5)
    assert session.event_key() == (1, 0)
    session.set_follow(True)
    assert session.event_key("dl1") == (1, 2)

    session.set_tel(2)
    assert session.selected_pixels == [] and session.tel_select.value == "TEL 2"
    refresh_all(session)
    assert session.pages[2].message.visible  # no R1 for TEL 2
    counters = session.pages[5].counters_source.data
    assert counters["tel"] == ["TEL 2"] and counters["rows"] == [1]


def test_without_subarray():
    store = ViewerStore()
    store.push_row("dl1", dl1_row(1))
    session = ViewerSession(store, Document())
    refresh_all(session)
    assert "geometry" in session.pages[4].message.text


def test_tick_refreshes_only_on_change(subarray):
    store, session = make_session(subarray)
    calls = []
    page = session.active_page
    page.refresh = lambda: calls.append(1)
    # the session was refreshed when created: nothing changed since
    session.tick()
    assert len(calls) == 0
    store.push_row("dl1", dl1_row(20))
    session.tick()
    session.tick()
    assert len(calls) == 1
    session.set_selected_pixels([1])
    session.tick()
    assert len(calls) == 2


def test_components(subarray):
    geometry = subarray.tel[1].camera.geometry
    panel = CameraPanel(geometry)
    panel.set_image(np.arange(geometry.n_pixels, dtype=float))
    assert panel.display.norm.high == geometry.n_pixels - 1
    panel.scale_select.value = "log"
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

    histogram = Histogram1DPanel("x", log_y=True)
    histogram.update(dict(edges=np.arange(4.0), counts=np.array([0, 2, 1]), n_entries=3, underflow=0, overflow=0,
                          n_invalid=0, mean=1.0, std=0.5))
    assert np.isnan(histogram.source.data["top"][0])
    assert histogram.figure.x_range.end == 3

    waveforms = np.arange(6.0).reshape(2, 3)
    assert list(camera_quantity(waveforms, "Maximum")) == [2, 5]
    assert list(camera_quantity(waveforms, "Sample", 1)) == [1, 4]


def test_server_application(subarray):
    """The bokeh application of the server creates a session in a document"""
    from sst1mpipe_viewer.server import make_server

    store = ViewerStore(subarray)
    server = make_server(store, port=0, refresh_period=2000)
    try:
        application = server._tornado.applications["/"].application
        doc = Document()
        application.initialize_document(doc)
        assert doc.title == "SST-1M Event Viewer"
        assert len(doc.session_callbacks) == 1
    finally:
        server.stop()
