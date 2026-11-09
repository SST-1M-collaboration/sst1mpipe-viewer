"""
Hillas parameters in the telescope frame from the parameters in the camera frame.

sst1mpipe writes the DL1 parameters in the camera frame (``camera_frame_hillas_x``,
``camera_frame_hillas_length``, ... in m), the viewer shows the cameras in the
``TelescopeFrame`` and uses the ctapipe telescope frame columns (``hillas_fov_lon``,
``hillas_length``, ... in deg). The centre of gravity and two points along the axes of the
ellipse are transformed with ctapipe, which gives the parameters whatever the orientation of the
camera frame.
"""

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from ctapipe.coordinates import TelescopeFrame

__all__ = ["CAMERA_FRAME_PREFIX", "add_telescope_frame_parameters", "source_telescope_frame"]

CAMERA_FRAME_PREFIX = "camera_frame_"
_REQUIRED = tuple(f"{CAMERA_FRAME_PREFIX}hillas_{name}" for name in ("x", "y", "length", "width", "psi"))
#: step along the axes of the ellipse (m), small with respect to the camera
_STEP = 0.01


def _to_telescope_frame(x, y, camera_frame):
    coord = SkyCoord(x=x * u.m, y=y * u.m, frame=camera_frame).transform_to(TelescopeFrame())
    return coord.fov_lon.to_value(u.deg), coord.fov_lat.to_value(u.deg)


def add_telescope_frame_parameters(columns, camera_frame):
    """
    Columns with the telescope frame Hillas and timing parameters (``hillas_fov_lon``,
    ``hillas_fov_lat``, ``hillas_r``, ``hillas_phi``, ``hillas_length``, ``hillas_width``,
    ``hillas_psi`` in deg, ``hillas_intensity``, ``hillas_skewness``, ``hillas_kurtosis``,
    ``timing_slope`` in ns/deg, ...) computed from the camera frame columns (m) of the rows of a
    telescope whose camera geometry is in ``camera_frame``. The columns are returned unchanged if
    they have the telescope frame parameters or not the camera frame ones.
    """
    if "hillas_fov_lon" in columns or not all(name in columns for name in _REQUIRED):
        return columns
    camera = {name: np.asarray(columns[name], dtype=float) for name in _REQUIRED}
    x, y = camera[_REQUIRED[0]], camera[_REQUIRED[1]]
    length, width, psi = camera[_REQUIRED[2]], camera[_REQUIRED[3]], np.deg2rad(camera[_REQUIRED[4]])

    lon, lat = _to_telescope_frame(x, y, camera_frame)
    along_lon, along_lat = _to_telescope_frame(x + _STEP * np.cos(psi), y + _STEP * np.sin(psi), camera_frame)
    across_lon, across_lat = _to_telescope_frame(x - _STEP * np.sin(psi), y + _STEP * np.cos(psi), camera_frame)
    # deg per m along each axis
    scale_length = np.hypot(along_lon - lon, along_lat - lat) / _STEP
    scale_width = np.hypot(across_lon - lon, across_lat - lat) / _STEP

    # orientation of the major axis in the telescope frame, in [-90, 90] deg: when the direction
    # of the axis is reversed, the skewness and the time gradient along it change sign
    psi_deg = np.rad2deg(np.arctan2(along_lat - lat, along_lon - lon))
    flip = np.where(np.abs(psi_deg) > 90, -1.0, 1.0)
    psi_deg = np.where(psi_deg > 90, psi_deg - 180, np.where(psi_deg < -90, psi_deg + 180, psi_deg))

    result = dict(columns)
    result.update(
        hillas_fov_lon=lon,
        hillas_fov_lat=lat,
        hillas_r=np.hypot(lon, lat),
        hillas_phi=np.rad2deg(np.arctan2(lat, lon)),
        hillas_length=length * scale_length,
        hillas_width=width * scale_width,
        hillas_psi=psi_deg,
    )
    copies = {"intensity": 1.0, "kurtosis": 1.0, "skewness": flip, "psi_uncertainty": 1.0,
              "length_uncertainty": scale_length, "width_uncertainty": scale_width,
              "transverse_cog_uncertainty": scale_width}
    for name, factor in copies.items():
        column = f"{CAMERA_FRAME_PREFIX}hillas_{name}"
        if column in columns:
            result[f"hillas_{name}"] = np.asarray(columns[column], dtype=float) * factor
    for name in ("intercept", "deviation"):
        column = f"{CAMERA_FRAME_PREFIX}timing_{name}"
        if column in columns:
            result[f"timing_{name}"] = np.asarray(columns[column], dtype=float)
    if f"{CAMERA_FRAME_PREFIX}timing_slope" in columns:
        # time gradient per m -> per deg along the major axis
        with np.errstate(invalid="ignore", divide="ignore"):
            result["timing_slope"] = (
                np.asarray(columns[f"{CAMERA_FRAME_PREFIX}timing_slope"], dtype=float) * flip / scale_length
            )
    return result


def source_telescope_frame(row, camera_frame):
    """
    Reconstructed source position of a DL2 row of sst1mpipe (``reco_src_x``, ``reco_src_y`` in m,
    camera frame) in the telescope frame: ``(fov_lon, fov_lat)`` in deg, None if unknown.
    """
    try:
        x, y = float(row["reco_src_x"]), float(row["reco_src_y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    lon, lat = _to_telescope_frame(np.array([x]), np.array([y]), camera_frame)
    return float(lon[0]), float(lat[0])
