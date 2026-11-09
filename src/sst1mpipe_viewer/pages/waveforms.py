"""Pages of the waveform data levels: R0, R1 and DL0"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Div, Select, Slider

from ..components import CameraPanel, FieldsTable, WaveformPanel
from ..components.waveform import waveform_2d
from .base import Page, event_description, message_div
from .trigger import TriggerTracesPanel

__all__ = ["WaveformPage"]

#: unit of the waveforms of each data level
WAVEFORM_UNITS = {"r0": "ADC counts", "r1": "p.e.", "dl0": "p.e."}

#: per pixel columns not shown as "pixel fields" (the waveforms, the baseline shown on its own)
EXCLUDED_FIELDS = ("waveform", "pedestal")

#: per pixel baseline of the waveforms (in their unit): the DigiCam pedestal of the R0 of sst1mpipe
BASELINE_FIELD = "pedestal"


def sample_image(waveforms, sample):
    """Values of the pixels at a sample of the waveforms ``(n_pixels, n_samples)`` (a view, no computation)"""
    return waveforms[:, min(max(int(sample), 0), waveforms.shape[1] - 1)]


def pixel_fields(row, n_pixels):
    """Names of the numeric per pixel columns of a row (shape (n_pixels,) or (n_channels, n_pixels))"""
    names = []
    for name, value in row.items():
        if name in EXCLUDED_FIELDS:
            continue
        value = np.asarray(value)
        if not (np.issubdtype(value.dtype, np.number) or value.dtype == bool):
            continue
        if value.shape == (n_pixels,) or (value.ndim == 2 and value.shape[1] == n_pixels):
            names.append(name)
    return names


class WaveformPage(Page):
    """Camera image computed from the waveforms, waveforms of the selected pixels, per pixel fields"""

    def __init__(self, session, kind):
        super().__init__(session)
        self.kind = kind
        self.title = kind.upper()
        unit = WAVEFORM_UNITS.get(kind, "")
        self.message = message_div()
        self.sample = Slider(title="Sample shown in the camera", start=0, end=1, value=0, step=1, width=350)
        self.channel = Select(title="Gain channel", value="0", options=["0"], width=100)
        for widget in (self.channel,):
            widget.on_change("value", lambda attr, old, new: self.refresh())
        self.sample.on_change("value_throttled", lambda attr, old, new: self.refresh())

        self.camera = CameraPanel(title=f"{self.title} waveform maximum", on_pixel_click=session.set_selected_pixels)
        self.waveforms = WaveformPanel(title=f"{self.title} waveforms", y_label=unit)
        self.fields = FieldsTable(width=440, height=470)
        self.baseline_camera = CameraPanel(title="DigiCam baseline (pedestal)", width=430, height=380,
                                           cmap="viridis", on_pixel_click=session.set_selected_pixels)
        # one camera per per-pixel field of the data (created when the fields are known)
        self.field_cameras = {}
        self.cameras_container = column()
        self.trigger = TriggerTracesPanel(session, on_change=self.refresh)
        self.layout = column(
            self.message,
            row(self.sample, self.channel),
            row(self.camera.layout, self.waveforms.layout, column(Div(text="<b>All the fields of the event</b>"),
                                                                  self.fields.layout)),
            Div(text="<h3 style='margin: 10px 0 0 0'>Fields per pixel</h3>"),
            self.cameras_container,
            self.trigger.layout,
        )

    def refresh(self):
        session = self.session
        geometry = session.geometry()
        key = session.event_key(self.kind)
        rows = self.store.event(session.tel_id, key) if key is not None else {}
        data = rows.get(self.kind)
        if geometry is None or data is None or "waveform" not in data:
            self.message.text = (
                "No camera geometry for this telescope (no subarray)." if geometry is None
                else f"No {self.title} data for TEL {session.tel_id}"
                + ("" if session.follow else " in this event") + "."
            )
            self.message.visible = True
            self.camera.set_caption(event_description(key, rows))
            self.camera.clear()
            for camera in self.field_cameras.values():
                camera.clear()
            self.baseline_camera.clear()
            self.waveforms.clear()
            self.fields.set_rows({})
            self.trigger.layout.visible = False
            return
        self.message.visible = False
        self.camera.set_caption(event_description(key, rows))
        self.camera.set_geometry(geometry)
        self.fields.set_rows({self.kind: data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})})

        waveform = np.asarray(data["waveform"])
        n_channels = waveform.shape[0] if waveform.ndim == 3 else 1
        channels = [str(i) for i in range(n_channels)]
        if self.channel.options != channels:
            self.channel.options = channels
            if self.channel.value not in channels:
                self.channel.value = channels[0]
        self.channel.visible = n_channels > 1
        waveforms = waveform_2d(waveform, int(self.channel.value))
        if waveforms.shape[0] != geometry.n_pixels:
            self.message.text = (
                f"The {self.title} waveforms have {waveforms.shape[0]} pixels,"
                f" the camera geometry {geometry.n_pixels}."
            )
            self.message.visible = True
            return
        n_samples = waveforms.shape[1]
        if self.sample.end != max(n_samples - 1, 1):
            self.sample.end = max(n_samples - 1, 1)
            self.sample.value = min(self.sample.value, n_samples - 1)

        sample = self.sample.value
        self.camera.set_title(f"{self.title} sample {sample} – TEL {session.tel_id}")
        self.camera.set_image(sample_image(waveforms, sample))
        pixels = session.selected_pixels
        self.camera.set_selected(pixels)
        baselines = data.get(BASELINE_FIELD)
        if baselines is not None and np.shape(baselines) != (geometry.n_pixels,):
            baselines = None
        self.waveforms.set_waveforms(waveforms, pixels, sample=sample, baselines=baselines)
        self.baseline_camera.layout.visible = baselines is not None
        if baselines is not None:
            self.baseline_camera.set_geometry(geometry)
            self.baseline_camera.set_title(f"DigiCam baseline (pedestal) – TEL {session.tel_id}")
            self.baseline_camera.set_caption("dashed lines on the waveforms")
            self.baseline_camera.set_image(np.asarray(baselines, dtype=float))
            self.baseline_camera.set_selected(session.selected_pixels)
        self.trigger.update(data, geometry)
        self.waveforms.figure.title.text = (
            f"{self.title} waveforms" + ("" if pixels else " (click on a pixel of the camera)")
        )

        self._show_pixel_fields(data, geometry)

    def _show_pixel_fields(self, data, geometry):
        """One camera per per-pixel field of the row (the gain channel of the page for 2D fields)"""
        session = self.session
        fields = pixel_fields(data, geometry.n_pixels)
        if list(self.field_cameras) != fields:
            cameras = {}
            for name in fields:
                cameras[name] = self.field_cameras.get(name) or CameraPanel(
                    title=name, width=430, height=380, cmap="viridis", on_pixel_click=session.set_selected_pixels)
            self.field_cameras = cameras
            panels = [self.baseline_camera.layout] + [camera.layout for camera in cameras.values()]
            self.cameras_container.children = [row(panels[i:i + 3]) for i in range(0, len(panels), 3)]
        for name, camera in self.field_cameras.items():
            values = np.asarray(data[name], dtype=float)
            if values.ndim == 2:
                values = values[min(int(self.channel.value), values.shape[0] - 1)]
            camera.set_geometry(geometry)
            camera.set_title(f"{name} – TEL {session.tel_id}")
            camera.set_image(values)
            camera.set_selected(session.selected_pixels)
