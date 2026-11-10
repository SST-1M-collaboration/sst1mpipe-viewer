"""
Configuration of the accumulated statistics of a data level (YAML files, see
``resources/dl1_statistics.yaml`` and ``resources/dl2_statistics.yaml``).

A configuration lists the histograms of the statistics page of the level:

- ``hist1d``: histograms of one column (``log_x: true`` for logarithmic bins and axis, the range
  being that of the values; ``log_y: true`` for a logarithmic axis of the entries);
- ``hist2d``: histograms of two columns (correlations; ``x_log`` / ``y_log`` for logarithmic bins).
"""

from importlib.resources import files
from pathlib import Path

import yaml

from .accumulators import Histogram1D, Histogram2D, StatisticsSet, make_bins

__all__ = ["STATISTICS_KINDS", "DEFAULT_STATISTICS_CONFIGS", "load_statistics_config", "build_statistics",
           "display_options"]

#: data levels with accumulated statistics
STATISTICS_KINDS = ("dl1", "dl2", "dl2_stereo")

#: default configuration file of each data level
DEFAULT_STATISTICS_CONFIGS = {
    kind: files("sst1mpipe_viewer") / "resources" / f"{kind}_statistics.yaml"
    for kind in (*STATISTICS_KINDS, "dl3")  # the DL3 statistics are not per telescope (sst1mpipe_viewer.dl3)
}

SECTIONS = ("hist1d", "hist2d")


def load_statistics_config(path=None, kind="dl1"):
    """
    Read a statistics configuration.

    Parameters
    ----------
    path : str, Path or None
        The YAML file; None for the default configuration of ``kind``.
    kind : str
        The data level (``"dl1"``, ``"dl2"``, ``"dl2_stereo"`` or ``"dl3"``), for the default configuration.

    Returns
    -------
    dict
        The configuration, ``{"hist1d": [...], "hist2d": [...]}``.
    """
    path = DEFAULT_STATISTICS_CONFIGS[kind] if path is None else Path(path)
    with path.open() as f:
        config = yaml.safe_load(f) or {}
    unknown = set(config) - set(SECTIONS)
    if unknown:
        raise ValueError(f"Unknown sections {sorted(unknown)} in the statistics configuration {path}"
                         f" (known: {list(SECTIONS)})")
    return config


def build_statistics(config):
    """
    Create the accumulators of a configuration (empty).

    Parameters
    ----------
    config : dict
        A statistics configuration (`load_statistics_config`).

    Returns
    -------
    StatisticsSet
    """
    statistics = StatisticsSet()
    for spec in config.get("hist1d", ()):
        spec = dict(spec)
        column = spec.pop("column")
        bins = make_bins(spec.pop("bins", 50), spec.pop("range", None), spec.pop("edges", None),
                         log=spec.pop("log_x", False))
        spec.pop("log_y", None)  # display option
        statistics.add(Histogram1D(name=spec.pop("name", column), column=column, bins=bins, **spec))
    for spec in config.get("hist2d", ()):
        spec = dict(spec)
        x, y = spec.pop("x"), spec.pop("y")
        x_bins = make_bins(spec.pop("x_bins", 40), spec.pop("x_range", None), spec.pop("x_edges", None),
                           log=spec.pop("x_log", False))
        y_bins = make_bins(spec.pop("y_bins", 40), spec.pop("y_range", None), spec.pop("y_edges", None),
                           log=spec.pop("y_log", False))
        name = spec.pop("name", f"{y}_vs_{x}")
        statistics.add(Histogram2D(name=name, x=x, y=y, x_bins=x_bins, y_bins=y_bins, **spec))
    return statistics


def display_options(config):
    """
    Display options of the histograms, by name: the logarithmic axes. ``{name: {"log_x": bool,
    "log_y": bool}}`` (for a 2D histogram, the axes of its ``x_log`` and ``y_log`` bins).
    """
    options = {}
    for spec in config.get("hist1d", ()):
        options[spec.get("name", spec["column"])] = {"log_x": bool(spec.get("log_x", False)),
                                                     "log_y": bool(spec.get("log_y", False))}
    for spec in config.get("hist2d", ()):
        options[spec.get("name", f"{spec['y']}_vs_{spec['x']}")] = {"log_x": bool(spec.get("x_log", False)),
                                                                   "log_y": bool(spec.get("y_log", False))}
    return options
