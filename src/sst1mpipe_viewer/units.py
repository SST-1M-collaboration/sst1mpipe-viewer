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
    # parameters in the camera frame (sst1mpipe)
    (re.compile(r"^camera_frame_hillas_(x|y|r|length|width)(_uncertainty)?$"), "m"),
    (re.compile(r"^camera_frame_hillas_transverse_cog_uncertainty$"), "m"),
    (re.compile(r"^camera_frame_hillas_(phi|psi)(_uncertainty)?$"), "deg"),
    (re.compile(r"^camera_frame_hillas_intensity$"), "p.e."),
    (re.compile(r"^camera_frame_timing_slope$"), "ns / m"),
    (re.compile(r"^camera_frame_timing_intercept$"), "ns"),
    # DL2 (ctapipe names with the algorithm as prefix, generic names and sst1mpipe names)
    (re.compile(r"^(.+_)?(reco_)?energy(_uncert)?$"), "TeV"),
    (re.compile(r"^(.+_)?(alt|az)(_uncert)?$"), "deg"),
    (re.compile(r"^(.+_)?(ang_distance_uncert|disp_parameter|tel_parameter)$"), "deg"),
    (re.compile(r"^(.+_)?(core(_tilted)?(_uncert)?_[xy]|h_max(_uncert)?|impact_distance(_uncert)?)$"), "m"),
    (re.compile(r"^reco_(src_x|src_y|disp_norm|disp_dx|disp_dy|core_x|core_y|h_max)$"), "m"),
)


def column_unit(name):
    """Display unit of a column, '' if unknown or without unit"""
    for pattern, unit in _UNITS:
        if pattern.match(name):
            return unit
    return ""
