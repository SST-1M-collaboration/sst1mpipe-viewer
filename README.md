# sst1mpipe-viewer

Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1) and of the statistics accumulated from
their DL1 parameters, based on [ctapipe](https://github.com/cta-observatory/ctapipe) (its bokeh
`CameraDisplay` and `ArrayDisplay`) and meant to show the data of
[sst1mpipe](https://github.com/SST-1M-collaboration/sst1mpipe) in real time.

## Pages

| Page | Content |
|---|---|
| **Overview** | Telescope array (click a telescope to select it), data received per telescope and data level (events, rates, last event) |
| **R0 / R1 / DL0** | Camera image computed from the waveforms (maximum, sum, a sample, time of maximum), waveforms of the selected pixels, any per pixel field of the data (e.g. `pixel_status`) |
| **DL1 Event** | Image and peak time with the cleaning mask and the Hillas ellipse, table of the DL1 parameters |
| **DL1 Statistics** | Accumulated histograms of the DL1 parameters, correlations, camera maps (fraction of events in which a pixel survives the cleaning, mean charge), with cuts and reset buttons (per plot, per telescope, all) |

The telescope is chosen at the top of the page. **Live** follows the last event, **◀ Prev** /
**Next ▶** browse the last events received. A click on a camera pixel selects it on all the
pages (shift+click adds or removes a pixel).

## Installation

```
pip install .
```

in an environment with ctapipe 0.32 (e.g. the sst1mpipe environment).

## Usage

```
sst1mpipe-viewer --demo tests/data/mrk421_tel21_tel22.dl1.h5 --rate 5
```

replays the Mrk 421 test file (DL1 of the two SST-1M telescopes processed by sst1mpipe, see
`tests/data/README.md`; `git lfs pull` to get it) at 5 events per second. Any ctapipe HDF5 file
written by `ctapipe-process` or `sst1mpipe-process`, with the DL1 images and parameters and
optionally the R1/DL0 waveforms, can be replayed the same way, and

```
sst1mpipe-viewer --demo run.simtel.gz
```

processes a file read by a ctapipe `EventSource` (calibration and DL1 parameters with the
default ctapipe configuration). The viewer is at http://localhost:5006/
(`--port`, `--allow-websocket-origin host:port` to reach it from another machine).
`sst1mpipe-viewer --help` lists the options (subarray, statistics configuration, refresh periods).

## Input of the viewer

The viewer displays the data pushed to a `ViewerStore`, from any thread:

```python
from sst1mpipe_viewer import ViewerStore, serve

store = ViewerStore(subarray)            # ctapipe SubarrayDescription: camera geometries, positions
store.push_event(event)                  # ctapipe ArrayEventContainer: R0, R1, DL0, DL1, trigger
store.push_container("dl1", event.dl1.tel[1], obs_id=obs_id, event_id=event_id, tel_id=1)
store.push_row("dl1", row)               # dict or astropy table row
store.push_table("dl1", table)           # astropy table, e.g. /dl1/event/telescope/parameters/tel_001
serve(store, port=5006)                  # blocking: push the data from another thread
```

The kinds of data are `r0`, `r1`, `dl0`, `dl1` and `trigger`. The columns are those of the
ctapipe HDF5 tables: a container is flattened as by the ctapipe `DataWriter` (its fields keep their
name, the fields of its sub-containers take their prefix: `image`, `peak_time`, `image_mask`,
`hillas_intensity`, `leakage_intensity_width_2`, ...). Every row needs `obs_id`, `event_id` and
`tel_id`; the rows of the same event of a telescope are merged (e.g. a DL1 image row and a DL1
parameter row). The statistics are filled with the `dl1` rows. The DL1 parameters in the camera frame written by
sst1mpipe (`camera_frame_hillas_*`, in m) are converted to the telescope frame (`hillas_fov_lon`,
`hillas_length`, ... in deg) with the camera geometry of the subarray.

The interface between the pipeline (files, ZMQ stream) and the viewer is not part of this package
yet: `sst1mpipe_viewer.demo` only replays files.

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
