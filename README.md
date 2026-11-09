# sst1mpipe-viewer

Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1) and of the statistics accumulated from
their DL1 parameters, based on [ctapipe](https://github.com/cta-observatory/ctapipe) (its bokeh
`CameraDisplay` and `ArrayDisplay`) and meant to show the data of
[sst1mpipe](https://github.com/SST-1M-collaboration/sst1mpipe) in real time.

## Pages

| Page | Content |
|---|---|
| **Overview** | Telescopes on an OpenStreetMap map at their Earth location (or in the ground frame), data received per telescope and data level; **pixel selection by group** of DigiCam (trigger patch, module, FADC board, CAN node, sector): a click on the camera of the groups selects all the pixels of a group, shift+click adds / removes a group, ids of groups can be entered (`0, 3-5`) |
| **R0 / R1 / DL0** | Every field of the data: the camera at the selected sample of the waveforms, the waveforms of the selected pixels (their mean for more than 10 pixels), one camera per per-pixel field (e.g. `pixel_flags`, `pixel_status`); for the R0 of DigiCam, the baseline (`pedestal`) camera and dashed lines on the waveforms, and the **trigger traces per trigger patch** (camera of the 432 triplets of pixels at the selected sample, traces of the patches of the selected pixels); the list of all the fields (values, shapes of the arrays, times, event types) |
| **DL1 Event** | Image and peak time with the cleaning mask and the Hillas ellipse, the list of all the DL1 and trigger fields |
| **DL1 Statistics** | Accumulated histograms of the DL1 parameters, correlations, camera maps (fraction of events in which a pixel survives the cleaning, mean charge), with cuts and reset buttons (per plot, per telescope, all) |

The viewer only reads the data as defined in the ctapipe / sst1mpipe containers: the cameras show
the values of a field (or of a sample of the waveforms), without computation.

The telescope is chosen at the top of the page. A click on a camera pixel selects it on all the
pages (shift+click adds or removes a pixel). The displayed event is chosen in the header:

- **Live**: the last event received (data pushed event by event, e.g. a stream);
- **◀ Prev** / **Next ▶**: the previous / next event;
- **Event id**: an `event_id`, or `#index` for the index of the event (`#0` the first, `#-1` the last).

## Installation

```
pip install .
```

in an environment with ctapipe 0.32 (e.g. the sst1mpipe environment).

## Usage

```
sst1mpipe-viewer tests/data/mrk421_tel21_tel22.h5
```

shows a file: all its events are processed at once (the DL1 statistics are those of all the
events of the file) and its first event is shown, any event can then be reached with Prev / Next
or its event id. The Mrk 421 test file has the R0, R1, DL0 and DL1 data of the two SST-1M
telescopes processed by sst1mpipe (see `tests/data/README.md`; `git lfs pull` to get it). Any
ctapipe HDF5 file written by `ctapipe-process` or `sst1mpipe-process` can be shown, several
files are read one after the other.

```
sst1mpipe-viewer tests/data/mrk421_tel21_tel22.h5 --replay-rate 1000 --loop
```

replays the events of the file one after the other at 1 kHz, as a live stream: the displays
follow the last event and the statistics are accumulated. A file read by a ctapipe
`EventSource` (e.g. `run.simtel.gz`) is processed event by event (calibration and DL1 parameters
with the default ctapipe configuration).

The viewer is at http://localhost:5006/ (`--port`, `--allow-websocket-origin host:port` to reach
it from another machine). `sst1mpipe-viewer --help` lists the options (subarray, statistics
configuration, refresh periods).

## Input of the viewer

The viewer displays the data pushed to a `ViewerStore`, from any thread:

```python
from sst1mpipe_viewer import ViewerStore, serve

store = ViewerStore(subarray)            # ctapipe SubarrayDescription: camera geometries, positions

# event by event (e.g. a stream): the last events are kept for the display
store.push_event(event)                  # ctapipe ArrayEventContainer: R0, R1, DL0, DL1, trigger
store.push_container("dl1", event.dl1.tel[1], obs_id=obs_id, event_id=event_id, tel_id=1)
store.push_row("dl1", row)               # dict or astropy table row

# a bunch of events (e.g. a file): processed at once, every event can be displayed
store.push_table("dl1", table)           # astropy table, e.g. /dl1/event/telescope/parameters/tel_001

serve(store, port=5006)                  # blocking: push the data from another thread
```

The kinds of data are `r0`, `r1`, `dl0`, `dl1` and `trigger`. The columns are those of the
ctapipe HDF5 tables: a container is flattened as by the ctapipe `DataWriter` (its fields keep their
name, the fields of its sub-containers take their prefix: `image`, `peak_time`, `image_mask`,
`hillas_intensity`, `leakage_intensity_width_2`, ...). Every row needs `obs_id`, `event_id` and
`tel_id`; the rows of the same event of a telescope are merged (e.g. a DL1 image row and a DL1
parameter row). The statistics are filled with the `dl1` rows. The DL1 parameters in the camera
frame written by sst1mpipe (`camera_frame_hillas_*`, in m) are converted to the telescope frame
(`hillas_fov_lon`, `hillas_length`, ... in deg) with the camera geometry of the subarray.

### Event rate

Pushing an event is cheap, so that the viewer follows streams of more than 1 kHz:

- the DL1 rows pushed event by event are buffered and fill the statistics in vectorized batches
  (when the statistics are displayed, or every `flush_size` rows); the camera frame parameters
  are converted to the telescope frame in these batches, and for the displayed event only;
- the R0, R1 and DL0 containers are converted only if their event is displayed (they must not be
  modified after being pushed: the ctapipe event sources create new containers for each event);
- the displays are refreshed every second with the last event (the events in between are not
  drawn), the statistics every 2 s (`--refresh-period`, `--statistics-period`).

Measured with the Mrk 421 file replayed at 1 kHz (`--replay-rate 1000 --loop`): the rate is held
with about 40 % of a CPU core for the server; `push_event` of calibrated ctapipe events takes
about 150 µs per telescope event.

The interface between the pipeline (files, ZMQ stream) and the viewer is not part of this package
yet: `sst1mpipe_viewer.feeds` only reads files.

## Statistics configuration

The accumulated statistics are defined in a YAML file (default:
`src/sst1mpipe_viewer/resources/dl1_statistics.yaml`, `--statistics-config` to use another one):

```yaml
cuts: ["hillas_intensity > 50"]
hist1d:
  - {column: hillas_intensity, transform: log10, range: [0, 5], bins: 50, log_y: true, apply_cuts: false}
  - {column: hillas_width, range: [0, 0.4], bins: 50, unit: deg}
hist2d:
  - {x: hillas_intensity, x_transform: log10, x_range: [1, 5], x_bins: 40, y: hillas_length, y_range: [0, 1], y_bins: 40}
camera:
  - {column: image_mask, mode: fraction}
```

The cuts can also be changed in the DL1 Statistics page (this resets the statistics).

## Tests

```
pip install .[test]
pytest
ruff check .
```
