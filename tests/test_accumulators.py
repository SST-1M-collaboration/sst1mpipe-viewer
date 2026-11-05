import numpy as np
import pytest

from sst1mpipe_viewer.accumulators import CameraAccumulator, Cut, Histogram1D, Histogram2D, StatisticsSet, make_bins
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


def test_cuts():
    assert str(Cut("hillas_intensity>50")) == "hillas_intensity > 50"
    with pytest.raises(ValueError):
        Cut("__import__('os')")

    statistics = StatisticsSet(
        [Histogram1D("x", "x", make_bins(2, (0, 2))), Histogram1D("all", "x", make_bins(2, (0, 2)), apply_cuts=False)],
        cuts=["s > 1"],
    )
    statistics.fill({"x": np.array([0.5, 1.5]), "s": np.array([0, 2])})
    assert statistics["x"].counts.tolist() == [0, 1]
    assert statistics["all"].counts.tolist() == [1, 1]
    # without the cut column, only the accumulators without cuts are filled
    statistics.fill({"x": np.array([0.5])})
    assert statistics["x"].n_entries == 1 and statistics["all"].n_entries == 3
    assert statistics.n_without_cut_columns == 1

    statistics.reset("x")
    assert statistics["x"].n_entries == 0 and statistics["all"].n_entries == 3
    statistics.set_cuts([])
    assert statistics["all"].n_entries == 0 and statistics.cuts == []


def test_default_configuration():
    statistics = build_statistics(load_statistics_config(), n_pixels=1296)
    names = {a.name for a in statistics}
    assert {"hillas_intensity", "hillas_length", "image_mask_fraction"} <= names
