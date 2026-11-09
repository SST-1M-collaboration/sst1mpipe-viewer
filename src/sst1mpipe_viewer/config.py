"""
Configuration of the accumulated statistics of a data level (YAML files, see
``resources/dl1_statistics.yaml`` and ``resources/dl2_statistics.yaml``).

A configuration lists the histograms of the statistics page of the level:

- ``hist1d``: histograms of one column;
- ``hist2d``: histograms of two columns (correlations);
- ``camera``: per pixel maps of an image column (DL1).
"""

from importlib.resources import files
from pathlib import Path

import yaml

from .accumulators import CameraAccumulator, Histogram1D, Histogram2D, StatisticsSet, make_bins

__all__ = ["STATISTICS_KINDS", "DEFAULT_STATISTICS_CONFIGS", "load_statistics_config", "build_statistics",
           "display_options"]

#: data levels with accumulated statistics
STATISTICS_KINDS = ("dl1", "dl2")

#: default configuration file of each data level
DEFAULT_STATISTICS_CONFIGS = {
    kind: files("sst1mpipe_viewer") / "resources" / f"{kind}_statistics.yaml" for kind in STATISTICS_KINDS
}

SECTIONS = ("hist1d", "hist2d", "camera")


def load_statistics_config(path=None, kind="dl1"):
    """
    Read a statistics configuration.

    Parameters
    ----------
    path : str, Path or None
        The YAML file; None for the default configuration of ``kind``.
    kind : str
        The data level (``"dl1"`` or ``"dl2"``), for the default configuration.

    Returns
    -------
    dict
        The configuration, ``{"hist1d": [...], "hist2d": [...], "camera": [...]}``.
    """
    path = DEFAULT_STATISTICS_CONFIGS[kind] if path is None else Path(path)
    with path.open() as f:
        config = yaml.safe_load(f) or {}
    unknown = set(config) - set(SECTIONS)
    if unknown:
        raise ValueError(f"Unknown sections {sorted(unknown)} in the statistics configuration {path}"
                         f" (known: {list(SECTIONS)})")
    return config


def build_statistics(config, n_pixels):
    """
    Create the accumulators of a configuration (empty).

    Parameters
    ----------
    config : dict
        A statistics configuration (`load_statistics_config`).
    n_pixels : int
        Number of pixels of the camera, for the camera maps.

    Returns
    -------
    StatisticsSet
    """
    statistics = StatisticsSet()
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
    """Display options of the 1D histograms, by name: ``{name: {"log_y": bool}}``"""
    options = {}
    for spec in config.get("hist1d", ()):
        options[spec.get("name", spec["column"])] = {"log_y": bool(spec.get("log_y", False))}
    return options
