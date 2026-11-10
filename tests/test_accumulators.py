import numpy as np
import pytest

from sst1mpipe_viewer.accumulators import CameraAccumulator, Histogram1D, Histogram2D, StatisticsSet, make_bins
from sst1mpipe_viewer.config import build_statistics, load_statistics_config


def test_histogram1d_fill_reset():
    h = Histogram1D("x", "x", make_bins(10, (0, 10)))
    h.fill({"x": np.array([-1, 0.5, 0.5, 9.5, 11, np.nan])})
    h.fill({"x": np.array([2.5])})  # one row or a table: same code
    assert h.counts.sum() == 4
    assert (h.underflow, h.overflow, h.n_invalid, h.n_entries) == (1, 1, 1, 7)
    assert h.counts[0] == 2 and h.counts[2] == 1
    h.reset()
    assert h.counts.sum() == 0 and h.n_entries == 0 and np.isnan(h.mean)


def test_histogram1d_log10_and_missing_column():
    h = Histogram1D("i", "intensity", make_bins(4, (0, 4)), transform="log10")
    h.fill({"intensity": np.array([10.0, 100.0, 0.0])})
    assert list(h.counts) == [0, 1, 1, 0]
    assert h.n_invalid == 1  # log10(0)
    h.fill({"other": np.array([1.0])})  # ignored
    assert h.n_entries == 3


def test_histogram2d_and_camera():
    h = Histogram2D("xy", "x", "y", make_bins(2, (0, 2)), make_bins(2, (0, 2)))
    h.fill({"x": np.array([0.5, 1.5]), "y": np.array([1.5, 1.5])})
    assert h.counts[0, 1] == 1 and h.counts[1, 1] == 1

    c = CameraAccumulator("mask", "image_mask", n_pixels=3, mode="fraction")
    c.fill({"image_mask": np.array([[True, False, False], [True, True, False]])})
    assert np.allclose(c.values, [1, 0.5, 0])
    c.fill({"image_mask": np.zeros((1, 4))})  # wrong number of pixels: ignored
    assert c.n_entries == 2

    c = CameraAccumulator("f", "image", n_pixels=2, mode="fraction")
    c.fill({"image": np.array([[np.nan, 1.0], [0.0, 0.0]])})
    assert np.allclose(c.values, [0, 0.5])  # the NaN value is not counted


def test_statistics_set():
    """Every row is accumulated (no cuts in the viewer); the accumulators without their columns are skipped"""
    bins = make_bins(2, (0, 2))
    statistics = StatisticsSet([Histogram1D("x", "x", bins), Histogram1D("y", "y", bins)])
    statistics.fill({"x": np.array([0.5, 1.5])})
    assert statistics["x"].counts.tolist() == [1, 1] and statistics["y"].n_entries == 0
    assert statistics.n_rows == 2
    statistics.reset("x")
    assert statistics["x"].n_entries == 0 and statistics.n_rows == 2
    statistics.reset()
    assert statistics.n_rows == 0


def test_default_configuration():
    statistics = build_statistics(load_statistics_config(), n_pixels=1296)
    names = {a.name for a in statistics}
    assert {"hillas_intensity", "hillas_length", "image_mask_fraction"} <= names


def test_default_dl2_configuration():
    statistics = build_statistics(load_statistics_config(kind="dl2"), n_pixels=1296)
    assert {"energy", "prediction", "alt", "az", "impact_distance"} <= {a.name for a in statistics}
    stereo = build_statistics(load_statistics_config(kind="dl2_stereo"), n_pixels=0)
    assert {"energy", "h_max", "core"} <= {a.name for a in stereo}


def test_log_bins():
    """log_x: logarithmic bins on the values (not a transform of the values)"""
    edges = make_bins(3, (1, 1000), log=True)
    assert np.allclose(edges, [1, 10, 100, 1000])
    with pytest.raises(ValueError):
        make_bins(3, (0, 10), log=True)
    statistics = build_statistics({"hist1d": [{"column": "e", "log_x": True, "range": [1, 1000], "bins": 3}],
                                   "hist2d": [{"x": "e", "x_log": True, "x_range": [1, 100], "x_bins": 2,
                                               "y": "g", "y_range": [0, 1], "y_bins": 1}]}, n_pixels=0)
    statistics.fill({"e": np.array([5.0, 50.0, 500.0]), "g": np.array([0.5, 0.5, 0.5])})
    assert statistics["e"].counts.tolist() == [1, 1, 1] and np.isclose(statistics["e"].mean, 185.0)
    assert statistics["g_vs_e"].counts[:, 0].tolist() == [1, 1]
