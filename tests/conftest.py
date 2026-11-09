import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import EarthLocation
from ctapipe.coordinates import CameraFrame
from ctapipe.instrument import (
    CameraDescription,
    CameraGeometry,
    CameraReadout,
    OpticsDescription,
    ReflectorShape,
    SizeType,
    SubarrayDescription,
    TelescopeDescription,
)

N_PIXELS_X = 10
N_PIXELS = N_PIXELS_X**2
N_SAMPLES = 20


def make_subarray(tel_ids=(1, 2)):
    """Subarray of telescopes with a small square camera (no data files needed)"""
    geometry = CameraGeometry.make_rectangular(N_PIXELS_X, N_PIXELS_X, range_x=(-0.4, 0.4), range_y=(-0.4, 0.4))
    geometry = CameraGeometry(
        name="TestCam", pix_id=geometry.pix_id, pix_x=geometry.pix_x, pix_y=geometry.pix_y,
        pix_area=geometry.pix_area, pix_type=geometry.pix_type,
        frame=CameraFrame(focal_length=5.6 * u.m),
    )
    readout = CameraReadout(
        name="TestCam", sampling_rate=250 * u.MHz, reference_pulse_shape=np.ones((1, 10)),
        reference_pulse_sample_width=1 * u.ns, n_channels=1, n_pixels=N_PIXELS, n_samples=N_SAMPLES,
    )
    optics = OpticsDescription(
        name="TestOptics", size_type=SizeType.SST, n_mirrors=1, equivalent_focal_length=5.6 * u.m,
        effective_focal_length=5.6 * u.m, mirror_area=9.4 * u.m**2, n_mirror_tiles=18,
        reflector_shape=ReflectorShape.HYBRID,
    )
    camera = CameraDescription("TestCam", geometry, readout)
    telescope = TelescopeDescription(name="TestTel", optics=optics, camera=camera)
    positions = {tel_id: [tel_id * 50.0, 0.0, 0.0] * u.m for tel_id in tel_ids}
    return SubarrayDescription(
        name="TestArray", tel_positions=positions, tel_descriptions={tel_id: telescope for tel_id in tel_ids},
        reference_location=EarthLocation(lon=14.78 * u.deg, lat=49.91 * u.deg, height=500 * u.m),
    )


def dl1_row(event_id, tel_id=1, intensity=100.0, obs_id=1):
    rng = np.random.default_rng(event_id)
    image = rng.normal(0, 1, N_PIXELS)
    mask = np.zeros(N_PIXELS, dtype=bool)
    mask[:5] = True
    return {
        "obs_id": obs_id, "event_id": event_id, "tel_id": tel_id,
        "image": image, "peak_time": rng.uniform(0, 80, N_PIXELS), "image_mask": mask,
        "hillas_intensity": intensity, "hillas_length": 0.2, "hillas_width": 0.05,
        "hillas_fov_lon": 0.5, "hillas_fov_lat": -0.5, "hillas_psi": 30.0, "hillas_r": 0.7,
    }


def r1_row(event_id, tel_id=1, obs_id=1):
    waveform = np.zeros((1, N_PIXELS, N_SAMPLES))
    waveform[0, 7, 5] = 10.0
    return {"obs_id": obs_id, "event_id": event_id, "tel_id": tel_id, "waveform": waveform,
            "pixel_status": np.full(N_PIXELS, 4)}


@pytest.fixture(scope="session")
def subarray():
    return make_subarray()


class Browser:
    """
    The pages of the viewer opened by a browser (one document each, sharing a UserState), in the
    order of the navigation; the other attributes are those of the first page (state, header)
    """

    def __init__(self, store):
        from bokeh.document import Document

        from sst1mpipe_viewer.app import PAGES, UserState, ViewerSession

        self.state = UserState(store)
        self.sessions = [ViewerSession(store, Document(), page=name, state=self.state) for name in PAGES]
        self.pages = [session.page for session in self.sessions]

    def __getattr__(self, name):
        return getattr(self.sessions[0], name)
