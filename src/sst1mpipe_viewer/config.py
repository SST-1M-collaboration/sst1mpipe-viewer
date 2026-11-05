"""Configuration of the accumulated statistics (YAML, see ``resources/dl1_statistics.yaml``)"""

from importlib.resources import files
from pathlib import Path

import yaml

from .accumulators import CameraAccumulator, Histogram1D, Histogram2D, StatisticsSet, make_bins

__all__ = ["DEFAULT_STATISTICS_CONFIG", "load_statistics_config", "build_statistics"]

DEFAULT_STATISTICS_CONFIG = files("sst1mpipe_viewer") / "resources" / "dl1_statistics.yaml"


def load_statistics_config(path=None):
    """Statistics configuration (dict) read from ``path``, the default one if None"""
    path = DEFAULT_STATISTICS_CONFIG if path is None else Path(path)
    with path.open() as f:
        config = yaml.safe_load(f) or {}
    unknown = set(config) - {"cuts", "hist1d", "hist2d", "camera"}
    if unknown:
        raise ValueError(f"Unknown sections {sorted(unknown)} in the statistics configuration {path}")
    return config


def build_statistics(config, n_pixels):
    """`StatisticsSet` of a statistics configuration, for a camera of ``n_pixels``"""
    statistics = StatisticsSet(cuts=config.get("cuts", ()))
    for spec in config.get("hist1d", ()):
        spec = dict(spec)
        column = spec.pop("column")
        bins = make_bins(spec.pop("bins", 50), spec.pop("range", None), spec.pop("edges", None))
        spec.pop("log_y", None)  # display option
        statistics.add(Histogram1D(name=spec.pop("name", column), column=column, bins=bins, **spec))
    for spec in config.get("hist2d", ()):
        spec = dict(spec)
        x, y = spec.pop("x"), spec.pop("y")
        x_bins = make_bins(spec.pop("x_bins", 40), spec.pop("x_range", None), spec.pop("x_edges", None))
        y_bins = make_bins(spec.pop("y_bins", 40), spec.pop("y_range", None), spec.pop("y_edges", None))
        name = spec.pop("name", f"{y}_vs_{x}")
        statistics.add(Histogram2D(name=name, x=x, y=y, x_bins=x_bins, y_bins=y_bins, **spec))
    for spec in config.get("camera", ()):
        spec = dict(spec)
        column = spec.pop("column")
        mode = spec.pop("mode", "mean")
        name = spec.pop("name", f"{column}_{mode}")
        statistics.add(CameraAccumulator(name=name, column=column, n_pixels=n_pixels, mode=mode, **spec))
    return statistics


def display_options(config):
    """Display options of the histograms by name (``log_y``)"""
    options = {}
    for spec in config.get("hist1d", ()):
        options[spec.get("name", spec["column"])] = {"log_y": bool(spec.get("log_y", False))}
    return options
