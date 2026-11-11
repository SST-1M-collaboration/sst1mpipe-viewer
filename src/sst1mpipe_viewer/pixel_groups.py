"""
Groups of pixels of the DigiCam camera: trigger patches, modules, FADC boards, CAN nodes and
sectors, from the camera configuration of CTS (``resources/digicam_pixel_groups.csv``, written by
``scripts/make_pixel_groups.py``). They select the pixels by group in the viewer.
"""

import csv
import re
from functools import cache
from importlib.resources import files

import astropy.units as u
import numpy as np

__all__ = ["GROUP_PALETTE", "group_color_indices", "GROUPINGS", "PixelGroups", "group_geometry", "parse_ids",
           "pixel_groups"]

#: label of each grouping -> column of the table
GROUPINGS = {
    "Pixel": "pixel",
    "Trigger patch": "patch",
    "Module": "module",
    "FADC board": "fadc_board",
    "CAN node": "can_node",
    "Sector": "sector",
}

def parse_ids(text):
    """Ids of a text like ``"3, 5-7 12"`` (separated by commas, semicolons or spaces, ranges included)"""
    ids = []
    for part in re.split(r"[,;\s]+", re.sub(r"\s*-\s*", "-", text.strip())):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if match is None:
            raise ValueError(f"Invalid id {part!r}: expected a number or a range like 3-7")
        first = int(match.group(1))
        last = first if match.group(2) is None else int(match.group(2))
        ids.extend(range(min(first, last), max(first, last) + 1))
    return ids


class PixelGroups:
    """Group ids of the pixels of a camera, ``ids[grouping][pixel]``"""

    def __init__(self, ids):
        self.ids = {name: np.asarray(values) for name, values in ids.items()}
        self.n_pixels = len(self.ids["pixel"])

    def matches(self, geometry):
        """Whether the groups are those of a camera geometry (same number of pixels and pixel ids)"""
        return geometry is not None and geometry.n_pixels == self.n_pixels and np.array_equal(
            np.sort(geometry.pix_id), np.sort(self.ids["pixel"]))

    def values(self, geometry, grouping):
        """Group id of each pixel of the geometry (in the order of the geometry)"""
        order = np.argsort(self.ids["pixel"])
        rows = np.searchsorted(self.ids["pixel"][order], np.asarray(geometry.pix_id))
        return self.ids[grouping][order][rows]

    def pixels(self, geometry, grouping, group_ids):
        """Indices in the geometry of the pixels of the groups ``group_ids``"""
        return np.flatnonzero(np.isin(self.values(geometry, grouping), list(group_ids))).tolist()

    def group_of(self, geometry, grouping, pixel):
        """Group id of a pixel (index in the geometry)"""
        return int(self.values(geometry, grouping)[pixel])

    def groups(self, geometry, grouping, pixels):
        """Sorted ids of the groups of pixels (indices in the geometry)"""
        return sorted({int(v) for v in self.values(geometry, grouping)[list(pixels)]})


@cache
def pixel_groups():
    """The `PixelGroups` of DigiCam"""
    with (files("sst1mpipe_viewer") / "resources" / "digicam_pixel_groups.csv").open() as f:
        rows = list(csv.DictReader(f))
    return PixelGroups({column: [int(row[column]) for row in rows] for column in GROUPINGS.values()})


#: colors of the groups of pixels: light and distinct, without red (the outline of the selection) nor grey
GROUP_PALETTE = ("#8dd3c7", "#ffffb3", "#bebada", "#80b1d3", "#fdb462", "#b3de69", "#fccde5", "#bc80bd")


def group_color_indices(geometry, values, n_colors=len(GROUP_PALETTE)):
    """
    Color of each pixel so that neighbouring groups of pixels have different colors.

    The groups are colored one after the other (graph coloring): a group takes a color which none
    of the groups touching it has, the least used so far, so that the colors are balanced.

    Parameters
    ----------
    geometry : ctapipe.instrument.CameraGeometry
        The pixels (their neighbours tell which groups touch each other).
    values : array
        Group of each pixel.
    n_colors : int
        Number of colors.

    Returns
    -------
    numpy array of int
        Index of the color of each pixel, in ``range(n_colors)``.
    """
    values = np.asarray(values)
    ids, group_index = np.unique(values, return_inverse=True)
    # groups touching each other: those with neighbouring pixels
    neighbors = geometry.neighbor_matrix_sparse.tocoo()
    touching = [set() for _ in ids]
    for a, b in zip(group_index[neighbors.row], group_index[neighbors.col]):
        if a != b:
            touching[a].add(int(b))
    colors = np.full(len(ids), -1)
    used = np.zeros(n_colors, dtype=int)
    for group in range(len(ids)):
        taken = {int(colors[other]) for other in touching[group] if colors[other] >= 0}
        free = [color for color in range(n_colors) if color not in taken] or list(range(n_colors))
        colors[group] = min(free, key=lambda color: used[color])
        used[colors[group]] += 1
    return colors[group_index]


def group_geometry(geometry, grouping="patch", groups=None):
    """
    Camera geometry of the groups of pixels of ``geometry`` (e.g. the 432 trigger patches of
    DigiCam, ``pix_id`` = patch_sw_id, the order of the trigger traces): each group is a hexagon
    at the centre of its pixels with their total area, rotated by 30 deg with respect to the pixels
    (the triplets of hexagonal pixels tile the camera as hexagons of 3 times their area).
    """
    from ctapipe.instrument import CameraGeometry

    groups = pixel_groups() if groups is None else groups
    values = groups.values(geometry, grouping)
    ids = np.unique(values)
    x = np.array([geometry.pix_x.value[values == i].mean() for i in ids])
    y = np.array([geometry.pix_y.value[values == i].mean() for i in ids])
    area = np.array([geometry.pix_area.value[values == i].sum() for i in ids])
    return CameraGeometry(
        name=f"{geometry.name}_{grouping}",
        pix_id=ids,
        pix_x=x * geometry.pix_x.unit,
        pix_y=y * geometry.pix_y.unit,
        pix_area=area * geometry.pix_area.unit,
        pix_type=geometry.pix_type,
        pix_rotation=geometry.pix_rotation + 30 * u.deg,
        cam_rotation=geometry.cam_rotation,
        frame=geometry.frame,
    )
