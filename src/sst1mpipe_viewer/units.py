"""Display units of the columns (their values are in the canonical units of `normalize`)"""

import re

__all__ = ["column_unit"]

_UNITS = (
    (re.compile(r"^hillas_(fov_lon|fov_lat|r|phi|length|width|psi)(_uncertainty)?$"), "deg"),
    (re.compile(r"^hillas_transverse_cog_uncertainty$"), "deg"),
    (re.compile(r"^hillas_(x|y)$"), "m"),
    (re.compile(r"^core_psi$"), "deg"),
    (re.compile(r"^timing_slope$"), "ns / deg"),
    (re.compile(r"^timing_intercept$"), "ns"),
    (re.compile(r"^peak_time_(max|min|mean|std)$"), "ns"),
    (re.compile(r"^(hillas_intensity|intensity_(max|min|mean|std))$"), "p.e."),
)


def column_unit(name):
    """Display unit of a column, '' if unknown or without unit"""
    for pattern, unit in _UNITS:
        if pattern.match(name):
            return unit
    return ""
