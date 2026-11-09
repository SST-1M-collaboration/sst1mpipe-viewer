"""Trigger traces of the DigiCam R0 data, displayed per trigger patch (triplet of pixels)"""

import numpy as np
from bokeh.layouts import column

from ..components import WaveformPanel
from ..pixel_groups import group_geometry, pixel_groups
from .pixel_selection import select_group

__all__ = ["TRACE_FIELDS", "TriggerView", "patch_geometry"]

#: trigger traces of the R0 data of sst1mpipe: (n_patches, n_samples), patch_sw_id order
#: (central patch of the clusters for the outputs)
TRACE_FIELDS = {
    "trigger_input_traces": "Trigger input (sum of the 3 pixels of each patch)",
    "trigger_output_patch7": "Trigger output, clusters of 7 patches",
    "trigger_output_patch19": "Trigger output, clusters of 19 patches",
    "trigger_output_muon": "Trigger output, muon clusters",
}

_PATCH_GEOMETRIES = {}


def patch_geometry(geometry):
    """Geometry of the trigger patches of a pixel geometry (cached), None if it is not DigiCam"""
    groups = pixel_groups()
    if geometry is None or not groups.matches(geometry):
        return None
    key = id(geometry)
    if key not in _PATCH_GEOMETRIES:
        _PATCH_GEOMETRIES[key] = (geometry, group_geometry(geometry, "patch", groups))
    return _PATCH_GEOMETRIES[key][1]


def trace_fields(row):
    """The trigger traces of a row"""
    return [name for name in TRACE_FIELDS if name in row and np.ndim(row[name]) == 2]


class TriggerView:
    """
    Trigger traces of a telescope: camera of the trigger patches
    (`sst1mpipe_viewer.pixel_groups.group_geometry`) at a sample of a trace, and the traces of the
    patches of the selected pixels. A click on a patch selects its 3 pixels (shift+click adds or
    removes them).
    """

    def __init__(self, session, tel_id, width=400, height=370):
        self.session = session
        self.tel_id = tel_id
        self.groups = pixel_groups()
        self.camera = session.camera_panel(geometry=patch_geometry(session.geometry(tel_id)),
                                           title="Trigger patches", on_pixel_tap=self.tapped, width=width,
                                           height=height)
        self.traces = WaveformPanel(title="Trigger traces", y_label="trigger trace", item_label="patch",
                                    width=520, height=height)
        self._pixel_geometry = None
        self.layout = column(self.camera.layout)

    def tapped(self, patch, shift):
        geometry = self._pixel_geometry
        patches = patch_geometry(geometry)
        if patches is None:
            return
        select_group(self.session, self.tel_id, self.groups.pixels(geometry, "patch", [int(patches.pix_id[patch])]),
                     shift)

    def clear(self):
        self.camera.clear()
        self.traces.clear()

    def update(self, data, geometry, trace, sample):
        """Show the trace ``trace`` of a R0 row at ``sample``"""
        patches = patch_geometry(geometry)
        if trace not in data or patches is None or np.shape(data[trace])[0] != patches.n_pixels:
            self.camera.set_title("No trigger traces")
            self.clear()
            return
        from .waveforms import sample_image

        traces = np.asarray(data[trace], dtype=float)
        sample = min(int(sample), traces.shape[1] - 1)
        self._pixel_geometry = geometry
        self.camera.set_geometry(patches)
        self.camera.set_image(sample_image(traces, sample))
        self.camera.set_title(f"{trace} sample {sample}")
        self.camera.set_caption(TRACE_FIELDS[trace])
        # patches of the selected pixels (index in the patch geometry = position of their patch_sw_id)
        selected = self.session.selected_pixels(self.tel_id)
        patch_ids = self.groups.groups(geometry, "patch", selected) if selected else []
        indices = np.searchsorted(patches.pix_id, patch_ids).tolist()
        self.camera.set_selected(indices)
        self.traces.set_waveforms(traces, indices, sample=sample)
        self.traces.figure.title.text = f"{trace}" + ("" if indices else " (click on a patch)")
