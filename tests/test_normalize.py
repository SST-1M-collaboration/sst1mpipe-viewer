import astropy.units as u
import numpy as np
from astropy.table import Table
from astropy.time import Time
from ctapipe.containers import DL1CameraContainer, EventType, HillasParametersContainer, ImageParametersContainer

from sst1mpipe_viewer.normalize import container_to_dict, iter_rows, n_rows, to_columns


def test_container_columns_are_those_of_the_ctapipe_tables():
    parameters = ImageParametersContainer(hillas=HillasParametersContainer(intensity=10.0, length=0.1 * u.deg))
    container = DL1CameraContainer(image=np.ones(3), peak_time=np.zeros(3), image_mask=np.ones(3, bool),
                                   parameters=parameters)
    flat = container_to_dict(container)
    assert {"image", "peak_time", "image_mask", "hillas_intensity", "leakage_intensity_width_2"} <= set(flat)

    columns = to_columns(container, obs_id=1, event_id=2, tel_id=3)
    assert n_rows(columns) == 1
    assert columns["image"].shape == (1, 3)
    assert columns["hillas_length"][0] == 0.1
    assert columns["tel_id"][0] == 3


def test_quantities_times_and_enums_are_converted():
    columns = to_columns({
        "length": 1 * u.arcmin, "time": Time(10.0, format="unix"), "event_type": EventType.SUBARRAY,
        "dimensionless": 2 * u.one, "missing": None,
    })
    assert np.isclose(columns["length"][0], 1 / 60)
    # a single time is kept as a Time (converted only to be shown)
    assert isinstance(columns["time"][0], Time) and np.isclose(columns["time"][0].unix, 10.0)
    assert columns["event_type"][0] == EventType.SUBARRAY.value
    assert columns["dimensionless"][0] == 2
    assert "missing" not in columns


def test_time_column_of_a_table():
    table = Table({"obs_id": [1, 1], "event_id": [1, 2], "time": Time([10.0, 20.0], format="unix")})
    assert np.allclose(to_columns(table)["time"], [10.0, 20.0])


def test_event_time_is_shown():
    from sst1mpipe_viewer.pages.base import event_description

    time = Time("2026-01-21T03:06:20", scale="utc")
    assert "2026-01-21T03:06:20" in event_description((1, 2), {"trigger": {"time": time}})
    assert "2026-01-21T03:06:20" in event_description((1, 2), {"trigger": {"time": time.unix}})


def test_table_rows():
    table = Table({"obs_id": [1, 1], "event_id": [1, 2], "x": [1.0, 2.0] * u.m, "image": np.zeros((2, 4))})
    columns = to_columns(table, tel_id=5)
    assert n_rows(columns) == 2
    assert list(columns["tel_id"]) == [5, 5]
    rows = list(iter_rows(columns))
    assert rows[1]["event_id"] == 2 and rows[1]["image"].shape == (4,)
    # a table row is one row
    assert n_rows(to_columns(table[0])) == 1
