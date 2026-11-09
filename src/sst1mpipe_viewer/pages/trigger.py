"""Trigger traces of the DigiCam R0 data, displayed per trigger patch (triplet of pixels)"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Div, Select, Slider

from ..components import CameraPanel, WaveformPanel
from ..pixel_groups import group_geometry, pixel_groups
from .pixel_selection import select_group

__all__ = ["TRACE_FIELDS", "TriggerTracesPanel"]

#: trigger traces of the R0 data of sst1mpipe: (n_patches, n_samples), patch_sw_id order
#: (central patch of the clusters for the outputs)
TRACE_FIELDS = {
    "trigger_input_traces": "Trigger input (sum of the 3 pixels of each patch)",
    "trigger_output_patch7": "Trigger output, clusters of 7 patches",
    "trigger_output_patch19": "Trigger output, clusters of 19 patches",
    "trigger_output_muon": "Trigger output, muon clusters",
}


class TriggerTracesPanel:
    """
    Camera of the trigger patches (`sst1mpipe_viewer.pixel_groups.group_geometry`) showing a
    trigger trace, and the traces of the patches of the selected pixels. A click on a patch
    selects its 3 pixels (shift+click adds or removes them).
    """

    def __init__(self, session, on_change=None):
        self.session = session
        self.groups = pixel_groups()
        self.trace = Select(title="Trigger trace", value="trigger_input_traces", options=list(TRACE_FIELDS), width=210)
        self.sample = Slider(title="Sample shown in the camera", start=0, end=1, value=0, step=1, width=350)
        if on_change is not None:
            self.trace.on_change("value", lambda attr, old, new: on_change())
            self.sample.on_change("value_throttled", lambda attr, old, new: on_change())
        self.camera = CameraPanel(title="Trigger patches", on_pixel_tap=self.tapped)
        self.traces = WaveformPanel(title="Trigger traces", y_label="trigger trace", item_label="patch")
        self.message = Div(text="", styles={"color": "#666"})
        self._geometries = {}
        self._pixel_geometry = None
        self.layout = column(
            Div(text="<h3 style='margin: 10px 0 0 0'>Trigger traces (per trigger patch: triplet of pixels)</h3>"),
            self.message,
            row(self.trace, self.sample),
            row(self.camera.layout, self.traces.layout),
        )

    def patch_geometry(self, geometry):
        """Geometry of the trigger patches of a pixel geometry (cached), None if not DigiCam"""
        if not self.groups.matches(geometry):
            return None
        key = id(geometry)
        if key not in self._geometries:
            self._geometries[key] = group_geometry(geometry, "patch", self.groups)
        return self._geometries[key]

    def tapped(self, patch, shift):
        geometry = self._pixel_geometry
        if geometry is None:
            return
        patch_geometry = self.patch_geometry(geometry)
        patch_id = int(patch_geometry.pix_id[patch])
        select_group(self.session, self.groups.pixels(geometry, "patch", [patch_id]), shift)

    def update(self, data, geometry):
        """Show the trigger traces of a R0 row (hidden if it has none)"""
        from .waveforms import sample_image

        fields = [name for name in TRACE_FIELDS if name in data and np.ndim(data[name]) == 2]
        self.layout.visible = bool(fields)
        if not fields:
            return
        if self.trace.options != fields:
            self.trace.options = fields
        if self.trace.value not in fields:
            self.trace.value = fields[0]
        patch_geometry = self.patch_geometry(geometry)
        traces = np.asarray(data[self.trace.value], dtype=float)
        if patch_geometry is None or traces.shape[0] != patch_geometry.n_pixels:
            self.message.text = "The trigger patches are those of DigiCam: not available for this camera."
            self.camera.layout.visible = False
            self.traces.clear()
            return
        self.message.text = ""
        self.camera.layout.visible = True
        self._pixel_geometry = geometry
        self.camera.set_geometry(patch_geometry)
        n_samples = traces.shape[1]
        if self.sample.end != max(n_samples - 1, 1):
            self.sample.end = max(n_samples - 1, 1)
            self.sample.value = min(self.sample.value, n_samples - 1)
        sample = self.sample.value
        self.camera.set_image(sample_image(traces, sample))
        self.camera.set_title(f"{self.trace.value} sample {sample} – TEL {self.session.tel_id}")
        self.camera.set_caption(TRACE_FIELDS[self.trace.value])

        # patches of the selected pixels (index in the patch geometry = position of their patch_sw_id)
        selected = self.session.selected_pixels
        patch_ids = self.groups.groups(geometry, "patch", selected) if selected else []
        patches = np.searchsorted(patch_geometry.pix_id, patch_ids).tolist()
        self.camera.set_selected(patches)
        self.traces.set_waveforms(traces, patches, sample=sample)
        self.traces.figure.title.text = f"{self.trace.value}" + ("" if patches else " (click on a patch)")
