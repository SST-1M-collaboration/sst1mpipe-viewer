# sst1mpipe-viewer

Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1, DL2, DL3) and of the statistics accumulated
from their DL1, DL2 and DL3 parameters, based on [ctapipe](https://github.com/cta-observatory/ctapipe) (its bokeh
`CameraDisplay` and `ArrayDisplay`) and meant to show the data of
[sst1mpipe](https://github.com/SST-1M-collaboration/sst1mpipe) in real time.

## Pages

One web page per data level, linked by the navigation bar at the top:

| Path | Page | Content |
|---|---|---|
| `/` | **Array** | **Selection of the telescopes** (check boxes, or click on a telescope of the map), each with its color used in all the pages; telescopes on an OpenStreetMap map at their Earth location (or in the ground frame); data received per telescope and data level, and **their rates in time** (one plot per telescope, one line per data level); **pixel selection by group**, one per telescope, of DigiCam (trigger patch, module, FADC board, CAN node, sector): a click on the camera of the groups selects all the pixels of a group, shift+click adds / removes a group, ids of groups can be entered (`0, 3-5`) |
| `/r0`, `/r1`, `/dl0` | **R0 / R1 / DL0** | Rate of the level in time; one block per selected telescope, with its own ◀ / ▶ (events of this telescope only) and its own **sample** slider, common to the waveform camera and the trigger traces: the camera at the selected sample of the waveforms, the waveforms of the selected pixels (their mean for more than 10 pixels), the camera of a per-pixel field chosen in a menu (the fields of the same shape, e.g. `pedestal`, `pixel_flags`, `pixel_status`, `selected_gain_channel`); for the R0 of DigiCam, dashed `pedestal` lines on the waveforms and the **trigger traces per trigger patch** (trace chosen in a menu, camera of the 432 triplets of pixels, traces of the patches of the selected pixels); the table of all the fields, one column per telescope |
| `/dl1` | **DL1 Event** | Rate of the level in time; per selected telescope (with its own ◀ / ▶): image, peak time or cleaning mask (menu) with the cleaning mask and the Hillas ellipse; the table of all the DL1 and trigger fields |
| `/dl1_statistics` | **DL1 Statistics** | Accumulated histograms of the DL1 parameters, superimposed with one color per telescope, correlations and camera maps (one plot per telescope), reset buttons (per plot, selected telescopes, all) |
| `/dl2` | **DL2 Event** | Rate of the level in time; per selected telescope: the DL1 image with the Hillas ellipse and the **reconstructed source position** (star); the table of all the DL2 fields (energy, gammaness, direction, ...) |
| `/dl2_statistics` | **DL2 Statistics** | Accumulated histograms of the DL2 parameters (reconstructed energy, gammaness, altitude, azimuth, disp), gammaness vs energy, reconstructed direction, source position in the camera |
| `/dl3` | **DL3** | Gamma-ray candidates of the observations (not per telescope): table of the observations (object, target, pointing, events, livetime), rate of the events in time, energy, θ² to the target, sky map around the target, position in the field of view (DETX / DETY) |

The pages opened by a browser share the selected telescopes, the displayed events and the selected
pixels (the client id `?c=...` of the links): going from a page to another keeps the context.

The viewer only reads and shows the data, as defined in the ctapipe / sst1mpipe containers: the
cameras show the values of a field (or of a sample of the waveforms), and every row received is
accumulated in the statistics (the selection of the events, e.g. cuts, belongs to the pipeline).

The telescopes are selected in the Array page only: every page shows the selected telescopes. A
click on a camera pixel selects it for its telescope on all the pages (shift+click adds or
removes a pixel); each telescope has its own selection. The displayed events are chosen in the
header:

- **Live**: the last event received (data pushed event by event, e.g. a stream);
- **◀ Prev** / **Next ▶**: the previous / next event of all the selected telescopes (◀ / ▶ next to
  a telescope name: of this telescope only);
- **Event id**: an `event_id`, or `#index` for the index of the event (`#0` the first, `#-1` the last).

The rates are shown per minute, with error bars for their statistical uncertainty (√N / duration):
by time of arrival for the data pushed event by event (the last 24 hours, the current minute
included), by time of the events for a file (the trigger times of its events). A dashed vertical
line marks the time of the displayed event of each telescope.

The color maps are not chosen in the pages (lighter pages) but on the command line: `--colormap`
(waveform and image cameras), `--field-colormap` (per-pixel fields), `--color-scale lin|log`.

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

The subarray (camera geometries, positions and Earth location of the telescopes) is read from
`--subarray FILE.h5`, by default the SST-1M subarray of sst1mpipe (`sst1m_array.h5`); the
telescopes of the files which are not in it are added.

The viewer is at http://localhost:5006/ (`--port`, `--allow-websocket-origin host:port` to reach
it from another machine). `sst1mpipe-viewer --help` lists the options (subarray, statistics
configuration, refresh periods).

## Input of the viewer

The viewer displays the data pushed to a `ViewerStore`, from any thread:

```python
from sst1mpipe_viewer import ViewerStore, serve

store = ViewerStore(subarray)            # ctapipe SubarrayDescription: camera geometries, positions

# event by event (e.g. a stream): the last events are kept for the display
store.push_event(event)                  # ctapipe ArrayEventContainer: R0, R1, DL0, DL1, DL2, trigger
store.push_container("dl1", event.dl1.tel[1], obs_id=obs_id, event_id=event_id, tel_id=1)
store.push_row("dl1", row)               # dict or astropy table row

# a bunch of events (e.g. a file): processed at once, every event can be displayed
store.push_table("dl1", table)           # astropy table, e.g. /dl1/event/telescope/parameters/tel_001

serve(store, port=5006)                  # blocking: push the data from another thread
```

The kinds of data are `r0`, `r1`, `dl0`, `dl1`, `dl2` and `trigger`. The columns are those of the
ctapipe HDF5 tables: a container is flattened as by the ctapipe `DataWriter` (its fields keep their
name, the fields of its sub-containers take their prefix: `image`, `peak_time`, `image_mask`,
`hillas_intensity`, `leakage_intensity_width_2`, ...). Every row needs `obs_id`, `event_id` and
`tel_id`; the rows of the same event of a telescope are merged (e.g. a DL1 image row and a DL1
parameter row). The statistics are filled with the `dl1` and `dl2` rows (`store.statistics(tel_id,
"dl2")`). The DL1 parameters in the camera
frame written by sst1mpipe (`camera_frame_hillas_*`, in m) are converted to the telescope frame
(`hillas_fov_lon`, `hillas_length`, ... in deg) with the camera geometry of the subarray.

DL2: the columns are those of sst1mpipe (`/dl2/event/telescope/parameters/tel_XXX`: `reco_energy`
in TeV, `gammaness`, `reco_alt`, `reco_az` in deg, `reco_src_x`, `reco_src_y` in m in the camera
frame, ...). The DL2 of ctapipe (`<algorithm>_tel_energy`, `<algorithm>_tel_prediction`,
`<algorithm>_tel_alt`, `<algorithm>_tel_az`, tables `/dl2/event/telescope/<group>/<algorithm>/tel_XXX`)
are shown under these names. The pipeline does not produce DL2 yet: to try the DL2 pages,
`scripts/make_synthetic_dl2.py` writes a copy of a DL1 file with **random** DL2 values:

```
python scripts/make_synthetic_dl2.py tests/data/mrk421_tel21_tel22.h5 /tmp/synthetic_dl2.h5
sst1mpipe-viewer /tmp/synthetic_dl2.h5
```

### Event rate

Pushing an event is cheap, so that the viewer follows streams of more than 1 kHz:

- the DL1 and DL2 rows pushed event by event are buffered and fill the statistics in vectorized batches
  (when the statistics are displayed, or every `flush_size` rows); the camera frame parameters
  are converted to the telescope frame in these batches, and for the displayed event only;
- the R0, R1 and DL0 containers are converted only if their event is displayed (they must not be
  modified after being pushed: the ctapipe event sources create new containers for each event);
- the page checks for new data every 250 ms (`--refresh-period`); the displayed event is
  redrawn at most every 0.5 s with the last event (the events in between are not drawn,
  `--event-period`), the statistics every 2 s (`--statistics-period`); every histogram entry is
  counted;
- a user action (click, menu, Prev / Next) is applied at once, without waiting for the next
  refresh; the changes of a refresh are sent to the browser in one message.

Measured with the Mrk 421 file (with synthetic DL2) replayed at 1 kHz (`--replay-rate 1000 --loop`):

| | file (no stream) | stream at 1 kHz |
|---|---|---|
| opening a page | 0.15–0.6 s | 0.25–0.9 s |
| refresh of an event page (median) | 4–7 ms | 5–35 ms |
| refresh of a statistics page (median) | 1–2 ms | 15–20 ms |

The rate is held (1000 events/s); `push_row` takes about 60 µs per row (170 µs per event of all
the data levels). At 1 kHz the feed thread and the bokeh server share the Python interpreter
(GIL), which slows the refreshes; running the ingest (reading the stream, filling the statistics)
in a separate process would remove this contention.

The interface between the pipeline (files, ZMQ stream) and the viewer is not part of this package
yet: `sst1mpipe_viewer.feeds` only reads files.

### DL3

A DL3 FITS file (GADF event list, as written by `sst1mpipe_data_dl2_dl3`) given on the command
line is read at once; from Python:

```python
from sst1mpipe_viewer.dl3 import read_dl3

store.dl3.push(*read_dl3("dl3_file.fits"))   # or store.dl3.push(events_table, header)
```

The columns are those of the `EVENTS` table (`TIME`, `RA`, `DEC`, `ENERGY`, `DETX`, `DETY`). The
only values computed by the viewer are the positions of the events relative to the target of their
observation (`RA_OBJ` / `DEC_OBJ` of the header, the pointing if missing): `offset_lon`,
`offset_lat` and `theta2`, once when the events are pushed. To try the page without DL3 data,
`scripts/make_synthetic_dl3.py` writes a file of **random** events:

```
python scripts/make_synthetic_dl3.py /tmp/synthetic_dl3.fits
sst1mpipe-viewer /tmp/synthetic_dl3.fits
```

## Statistics configuration

The accumulated statistics of each data level are defined in a YAML file (defaults:
`src/sst1mpipe_viewer/resources/dl1_statistics.yaml`, `dl2_statistics.yaml` and
`dl3_statistics.yaml`; `--statistics-config`, `--dl2-statistics-config` and
`--dl3-statistics-config` to use others):

```yaml
hist1d:
  - {column: hillas_intensity, transform: log10, range: [0, 5], bins: 50, log_y: true}
  - {column: hillas_width, range: [0, 0.4], bins: 50, unit: deg}
hist2d:
  - {x: hillas_intensity, x_transform: log10, x_range: [1, 5], x_bins: 40, y: hillas_length, y_range: [0, 1], y_bins: 40}
camera:
  - {column: image_mask, mode: fraction}
```

## Code organisation

| Module | Role |
|---|---|
| `store.py` | `ViewerStore`: the data received (events, tables) and the accumulated statistics; the input of the viewer |
| `normalize.py` | Conversion of the inputs (containers, rows, tables) to columns `{name: numpy array}` |
| `accumulators.py`, `config.py` | Histograms and camera maps, and their YAML configuration |
| `frames.py`, `dl2.py`, `units.py` | Camera → telescope frame of the sst1mpipe parameters, DL2 column names, display units |
| `dl3.py` | DL3 event lists: reading of the FITS files, accumulated histograms, offsets to the target |
| `feeds.py` | Reading of files (HDF5 tables, ctapipe `EventSource`) into a store |
| `app.py`, `server.py`, `cli.py` | Bokeh pages (header, navigation, state shared by the pages of a browser), server, command line |
| `pages/` | One module per kind of page: `array.py`, `waveforms.py` (+ `trigger.py`), `events.py` (DL1 / DL2 Event), `statistics.py`, `dl3.py`, `pixel_selection.py` |
| `components/` | Bokeh displays independent of the store: camera, waveforms, histograms, rates, array map, fields table |
| `pixel_groups.py`, `colors.py` | DigiCam pixel groups (from CTS), colors of the telescopes |

## Tests

```
pip install .[test]
pytest
ruff check .
```
