"""Pages of the waveform data levels: R0, R1 and DL0"""

import numpy as np
from bokeh.layouts import column, row
from bokeh.models import Div, Select, Slider

from ..components import FieldsTable, WaveformPanel
from ..components.waveform import waveform_2d
from .base import LevelRates, Page, event_description, message_div, set_stale, stale_message, telescope_header
from .trigger import TRACE_FIELDS, TriggerView, trace_fields

__all__ = ["WaveformPage", "field_shapes", "sample_image"]

#: unit of the waveforms of each data level
WAVEFORM_UNITS = {"r0": "ADC counts", "r1": "p.e.", "dl0": "p.e."}

#: per pixel baseline of the waveforms (in their unit): the DigiCam pedestal of the R0 of sst1mpipe,
#: also drawn as dashed lines on the waveforms
BASELINE_FIELD = "pedestal"


def sample_image(waveforms, sample):
    """Values of the pixels at a sample of the waveforms ``(n_pixels, n_samples)`` (a view, no computation)"""
    return waveforms[:, min(max(int(sample), 0), waveforms.shape[1] - 1)]


def field_shapes(row, n_pixels):
    """
    Numeric array fields of a row grouped by shape (fields of the same shape are shown in the
    same camera, chosen in a menu):

    - ``"pixel"``: one value per pixel, ``(n_pixels,)`` or ``(n_channels, n_pixels)``
      (e.g. ``pedestal``, ``pixel_flags``, ``pixel_status``, ``selected_gain_channel``);
    - ``"pixel_sample"``: waveforms, ``(n_pixels, n_samples)`` or ``(n_channels, n_pixels, n_samples)``.
    """
    groups = {"pixel": [], "pixel_sample": []}
    for name, value in row.items():
        value = np.asarray(value)
        if value.ndim == 0 or not (np.issubdtype(value.dtype, np.number) or value.dtype == bool):
            continue
        shape = value.shape
        if shape == (n_pixels,) or (len(shape) == 2 and shape[1] == n_pixels):
            groups["pixel"].append(name)
        elif (len(shape) == 2 and shape[0] == n_pixels) or (len(shape) == 3 and shape[1] == n_pixels):
            groups["pixel_sample"].append(name)
    return groups


def set_options(select, options):
    """Options of a menu (sent only if they changed), its value one of them"""
    if list(select.options) != options:
        select.options = options
    if options and select.value not in options:
        select.value = options[0]


def _union(lists):
    """Names of several lists, without duplicates, in the order of first appearance"""
    result = []
    for names in lists:
        result += [name for name in names if name not in result]
    return result


class _TelescopeWaveforms:
    """Displays of the event of a telescope in a waveform page"""

    def __init__(self, page, tel_id):
        session = page.session
        self.session, self.page, self.tel_id = session, page, tel_id
        self.header = telescope_header(session, tel_id)
        self.message = message_div()
        # the sample of the waveforms and of the trigger traces shown in the cameras (per telescope)
        self.sample = Slider(title="Sample", start=0, end=1, value=0, step=1, width=400)
        self.sample.on_change("value_throttled", lambda attr, old, new: page.refresh())
        # the cameras are created with their geometry (cheaper than setting it later)
        geometry = session.geometry(tel_id)
        self.camera = session.camera_panel(geometry=geometry, title="Waveforms",
                                           on_pixel_click=session.pixel_click(tel_id), width=400, height=370)
        self.waveforms = WaveformPanel(title="Waveforms", y_label=WAVEFORM_UNITS.get(page.kind, ""), width=520,
                                       height=370)
        self.field_camera = session.camera_panel(geometry=geometry, title="Pixel field", cmap=session.field_colormap,
                                                 on_pixel_click=session.pixel_click(tel_id), width=400,
                                                 height=370)
        self.trigger = TriggerView(session, tel_id) if page.kind == "r0" else None
        rows = [row(self.camera.layout, self.waveforms.layout, self.field_camera.layout)]
        if self.trigger is not None:
            rows.append(row(self.trigger.layout, self.trigger.traces.layout))
        # the displays are blurred when they are not those of the current event (`show_status`)
        self.displays = column(*rows)
        self.layout = column(row(self.header, self.sample, self.message), self.displays)
        self.shown = False  # an event is displayed

    def set_sample_range(self, n_samples):
        """Range of the sample slider: the samples of the waveforms and of the trigger traces"""
        end = max(n_samples - 1, 1)
        if self.sample.end != end:
            self.sample.end = end
            if self.sample.value > end:
                self.sample.value = end

    def show_status(self, message, stale=False):
        """
        Show a message above the displays (None for none) and blur the displays if they are
        ``stale``: those of another event than the current one
        """
        if self.message.text != (message or ""):
            self.message.text = message or ""
        set_stale(self.displays, stale)

    def clear(self, message):
        """Show no event, with a message (e.g. why there is no data)"""
        self.shown = False
        self.show_status(message)
        self.camera.clear()
        self.field_camera.clear()
        self.waveforms.clear()
        if self.trigger is not None:
            self.trigger.clear()

    def update(self, key, rows, data, geometry):
        """Show the event ``key`` (its rows ``{kind: row}``, ``data`` the row of the page)"""
        page, session = self.page, self.session
        self.shown = True
        self.camera.set_caption(event_description(key, rows))
        self.camera.set_geometry(geometry)
        self.field_camera.set_geometry(geometry)
        pixels = session.selected_pixels(self.tel_id)
        channel = int(page.channel.value)

        name = page.waveform_field.value
        if name in data:
            waveforms = waveform_2d(np.asarray(data[name]), channel)
            sample = min(self.sample.value, waveforms.shape[1] - 1)
            self.camera.set_title(f"{name} sample {sample}")
            self.camera.set_image(sample_image(waveforms, sample))
            self.camera.set_selected(pixels)
            baselines = data.get(BASELINE_FIELD)
            if baselines is not None and np.shape(baselines) != (geometry.n_pixels,):
                baselines = None
            self.waveforms.set_waveforms(waveforms, pixels, sample=sample, baselines=baselines)
            self.waveforms.figure.title.text = name + ("" if pixels else " (click on a pixel of the camera)")
        else:
            self.camera.clear()
            self.waveforms.clear()

        name = page.pixel_field.value
        if name in data:
            values = np.asarray(data[name], dtype=float)
            if values.ndim == 2:
                values = values[min(channel, values.shape[0] - 1)]
            self.field_camera.set_title(name)
            self.field_camera.set_caption("dashed lines on the waveforms" if name == BASELINE_FIELD else "")
            self.field_camera.set_image(values)
            self.field_camera.set_selected(pixels)
        else:
            self.field_camera.clear()

        if self.trigger is not None:
            self.trigger.update(data, geometry, page.trace.value, self.sample.value)


class WaveformPage(Page):
    """
    The events of the selected telescopes (one block per telescope, with its color, its own
    Prev / Next and its own sample, common to the waveforms and the trigger traces): camera of a
    sample of the waveforms, waveforms of the selected pixels, camera of a per pixel field, and for
    the R0 of DigiCam the trigger traces per trigger patch; the fields of the same shape are chosen
    in a menu, common to the telescopes. The table has all the fields of the events. The layout only
    changes when the selected telescopes change.
    """

    def __init__(self, session, kind):
        super().__init__(session)
        self.kind = kind
        self.title = kind.upper()
        self.channel = Select(title="Gain channel", value="0", options=["0"], width=100)
        self.waveform_field = Select(title="Waveforms", value="waveform", options=["waveform"], width=180)
        self.pixel_field = Select(title="Pixel field", value="", options=[], width=200)
        self.trace = Select(title="Trigger trace", value="trigger_input_traces", options=list(TRACE_FIELDS),
                            width=210)
        for widget in (self.channel, self.waveform_field, self.pixel_field, self.trace):
            widget.on_change("value", lambda attr, old, new: self.refresh())
        controls = [self.waveform_field, self.channel, self.pixel_field]
        if kind == "r0":
            controls += [self.trace]
        self.rates = LevelRates(session, kind)
        self.views = {tel_id: _TelescopeWaveforms(self, tel_id) for tel_id in session.all_tel_ids}
        self.views_container = column()
        self.fields = FieldsTable(width=1000, height=400)
        self._shown_tel_ids = None
        self.layout = column(
            self.rates.layout,
            row(*controls),
            self.views_container,
            Div(text="<h3 style='margin: 10px 0 0 0'>All the fields of the events</h3>"),
            self.fields.layout,
        )

    def _set_views(self, tel_ids):
        """Blocks of the selected telescopes (changed only when the selection changes)"""
        for tel_id in tel_ids:
            if tel_id not in self.views:  # telescope added after the page was built
                self.views[tel_id] = _TelescopeWaveforms(self, tel_id)
        if tel_ids != self._shown_tel_ids:
            self._shown_tel_ids = tel_ids
            self.views_container.children = [self.views[t].layout for t in tel_ids]

    def refresh(self):
        """Show the displayed event of each selected telescope, the menus and the fields table"""
        session = self.session
        tel_ids = session.tel_ids
        self._set_views(tel_ids)
        self.rates.refresh()
        events = {}
        for tel_id in tel_ids:
            geometry = session.geometry(tel_id)
            key = session.event_key(tel_id, self.kind)
            rows = self.store.event(tel_id, key, (self.kind, "trigger")) if key is not None else {}
            data = rows.get(self.kind)
            shapes = field_shapes(data, geometry.n_pixels) if data is not None and geometry is not None else None
            events[tel_id] = (key, rows, data, geometry, shapes)

        # the menus: the fields of the displayed events
        shown = {t: e for t, e in events.items() if e[4] is not None and e[4]["pixel_sample"]}
        set_options(self.waveform_field, _union(e[4]["pixel_sample"] for e in shown.values()))
        set_options(self.pixel_field, _union(e[4]["pixel"] for e in shown.values()))
        if self.kind == "r0":
            set_options(self.trace, _union(trace_fields(e[2]) for e in shown.values()) or list(TRACE_FIELDS))
        n_channels = 1
        for tel_id, (_, _, data, _, _) in shown.items():
            n_samples = 1
            if self.waveform_field.value in data:
                shape = np.shape(data[self.waveform_field.value])
                n_channels = max(n_channels, shape[0] if len(shape) == 3 else 1)
                n_samples = shape[-1]
            if self.kind == "r0" and self.trace.value in data:
                n_samples = max(n_samples, np.shape(data[self.trace.value])[-1])
            self.views[tel_id].set_sample_range(n_samples)
        set_options(self.channel, [str(i) for i in range(n_channels)])

        table = {}
        for tel_id, (key, rows, data, geometry, shapes) in events.items():
            view = self.views[tel_id]
            has_data = tel_id in shown
            message = stale_message(session, tel_id, self.kind, key, has_data)
            if has_data:
                view.update(key, rows, data, geometry)
                table[tel_id] = {self.kind: data, **({"trigger": rows["trigger"]} if "trigger" in rows else {})}
                view.show_status(message, stale=message is not None)
            elif geometry is None:
                view.clear("No camera geometry (no subarray).")
            elif view.shown:
                # the displays of the last event shown are kept, blurred: they are not those of the current event
                view.show_status(message + " The displays are those of another event.", stale=True)
            else:
                view.clear(message)
        self.fields.set_rows(table)
