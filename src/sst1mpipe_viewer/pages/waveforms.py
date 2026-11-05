"""Pages of the waveform data levels: R0, R1 and DL0"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Select, Slider

from ..components import CameraPanel, WaveformPanel
from ..components.waveform import waveform_2d
from .base import Page, event_description, message_div

__all__ = ["WaveformPage"]

QUANTITIES = ("Maximum", "Sum", "Sample", "Time of maximum")

#: unit of the waveforms of each data level
WAVEFORM_UNITS = {"r0": "ADC counts", "r1": "p.e.", "dl0": "p.e."}

#: per pixel columns not shown as "pixel fields"
EXCLUDED_FIELDS = ("waveform",)


def camera_quantity(waveforms, quantity, sample=0):
    """Per pixel quantity of waveforms ``(n_pixels, n_samples)``"""
    waveforms = np.asarray(waveforms, dtype=float)
    if quantity == "Maximum":
        return waveforms.max(axis=1)
    if quantity == "Sum":
        return waveforms.sum(axis=1)
    if quantity == "Sample":
        return waveforms[:, min(int(sample), waveforms.shape[1] - 1)]
    if quantity == "Time of maximum":
        return waveforms.argmax(axis=1).astype(float)
    raise ValueError(f"Unknown quantity {quantity!r}")


def brightest_pixel(waveforms):
    """Pixel of the highest waveform sample (0 if all the waveforms are NaN)"""
    maxima = np.asarray(waveforms, dtype=float).max(axis=1)
    return int(np.nanargmax(maxima)) if np.isfinite(maxima).any() else 0


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
        self.quantity = Select(title="Camera image", value="Maximum", options=list(QUANTITIES), width=150)
        self.sample = Slider(title="Sample", start=0, end=1, value=0, step=1, width=250, disabled=True)
        self.channel = Select(title="Gain channel", value="0", options=["0"], width=100)
        self.field = Select(title="Pixel field", value="", options=[], width=200)
        for widget in (self.quantity, self.channel, self.field):
            widget.on_change("value", lambda attr, old, new: self.refresh())
        self.sample.on_change("value_throttled", lambda attr, old, new: self.refresh())
        self.quantity.on_change("value", lambda attr, old, new: setattr(self.sample, "disabled", new != "Sample"))

        self.camera = CameraPanel(title=f"{self.title} waveform maximum", on_pixel_click=session.set_selected_pixels)
        self.waveforms = WaveformPanel(title=f"{self.title} waveforms", y_label=unit)
        self.field_camera = CameraPanel(title="Pixel field", width=380, height=340, cmap="viridis",
                                        on_pixel_click=session.set_selected_pixels)
        self.layout = column(
            self.message,
            row(self.quantity, self.sample, self.channel, self.field),
            row(self.camera.layout, self.waveforms.layout),
            self.field_camera.layout,
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
            self.field_camera.clear()
            self.waveforms.clear()
            return
        self.message.visible = False
        self.camera.set_caption(event_description(key, rows))
        self.camera.set_geometry(geometry)
        self.field_camera.set_geometry(geometry)

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

        quantity = self.quantity.value
        image = camera_quantity(waveforms, quantity, self.sample.value)
        label = quantity.lower() if quantity != "Sample" else f"sample {self.sample.value}"
        self.camera.set_title(f"{self.title} {label} – TEL {session.tel_id}")
        self.camera.set_image(image)
        pixels = session.selected_pixels or [brightest_pixel(waveforms)]
        self.camera.set_selected(session.selected_pixels)
        sample = self.sample.value if quantity == "Sample" else None
        self.waveforms.set_waveforms(waveforms, pixels, sample=sample)
        self.waveforms.figure.title.text = (
            f"{self.title} waveforms" + ("" if session.selected_pixels else " (brightest pixel, click to select)")
        )

        fields = pixel_fields(data, geometry.n_pixels)
        if self.field.options != fields:
            self.field.options = fields
        if fields and self.field.value not in fields:
            self.field.value = fields[0]
            return  # refreshed by the change of the field
        self.field_camera.layout.visible = bool(fields)
        if fields:
            values = np.asarray(data[self.field.value], dtype=float)
            if values.ndim == 2:
                values = values[min(int(self.channel.value), values.shape[0] - 1)]
            self.field_camera.set_title(f"{self.field.value} – TEL {session.tel_id}")
            self.field_camera.set_image(values)
            self.field_camera.set_selected(session.selected_pixels)
