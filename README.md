# sst1mpipe-viewer

Bokeh viewer of the SST-1M events (R0, R1, DL0, DL1, DL2, DL3) and of the statistics accumulated
from their DL1, DL2 and DL3 parameters, based on [ctapipe](https://github.com/cta-observatory/ctapipe) (its bokeh
`CameraDisplay` and `ArrayDisplay`) and meant to show the data of
[sst1mpipe](https://github.com/SST-1M-collaboration/sst1mpipe) in real time.

## Pages

One web page per data level, linked by the navigation bar at the top:

| Path | Page | Content |
|---|---|---|
| `/` | **Array** | Telescopes on an OpenStreetMap map at their Earth location (or in the ground frame), each with its color used in all the pages (a click on a telescope selects or unselects it); **rates of the data levels in time** (one plot per telescope, one line per data level) |
| `/selection` | **Selection** | **Selection of the telescopes** (check boxes) and **of the pixels by group**, one panel per telescope, of DigiCam (trigger patch, module, FADC board, CAN node, sector): a click on the camera of the groups selects all the pixels of a group, shift+click adds / removes a group, ids of groups can be entered (`0, 3-5`); neighbouring groups have different colors |
| `/r0`, `/r1`, `/dl0` | **R0 / R1 / DL0** | Rate of the level in time; one block per selected telescope, with its own ◀ / ▶ (events of this telescope only) and its own **sample** slider, common to the waveform camera and the trigger traces: the camera at the selected sample of the waveforms, the waveforms of the selected pixels (their mean for more than 12 pixels: the 12 pixels of a module are all drawn), the camera of a per-pixel field chosen in a menu (the fields of the same shape, e.g. `pedestal`, `pixel_flags`, `pixel_status`, `selected_gain_channel`); for the R0 of DigiCam, dashed `pedestal` lines on the waveforms and the **trigger traces per trigger patch** (trace chosen in a menu, camera of the 432 triplets of pixels, traces of the patches of the selected pixels); the table of all the fields, one column per telescope |
| `/dl1` | **DL1** | Rate of the level in time; per selected telescope (with its own ◀ / ▶): image, peak time or cleaning mask (menu) with the cleaning mask and the Hillas ellipse; the table of all the DL1 and trigger fields |
| `/dl1_statistics` | **DL1 Statistics** | Accumulated histograms of the DL1 parameters, superimposed with one color per telescope, correlations (one plot per telescope) |
| `/dl2` | **DL2** | Rate of the level in time; per selected telescope: the DL1 image with the Hillas ellipse, and the table of **all the DL2 fields of the telescope** (every algorithm: geometry, energy, classification, impact, disp, with their uncertainties, validity and goodness of fit) |
| `/dl2_statistics` | **DL2 Statistics** | Per telescope, **the algorithm of each group chosen in a menu** (geometry, energy, classification, impact, disp): reconstructed energy and its uncertainty, gammaness, altitude, azimuth, impact distance, disp, validity flags; gammaness vs energy, direction, impact vs energy |
| `/dl2_stereo` | **DL2 Stereo** | The stereo reconstruction of the subarray (not per telescope): rate; the displayed stereo event with its own ◀ / ▶ (reconstructed core on the ground with the telescopes, those used ringed, and the table of all its fields); statistics of all the stereo events with the algorithm menus (energy, gammaness, direction, h_max, core map, ...) |
| `/dl3` | **DL3** | Gamma-ray candidates of the observations (not per telescope): table of the observations (object, target, pointing, events, livetime), rate of the events in time, energy, θ² to the target, sky map around the target, position in the field of view (DETX / DETY) |

The pages opened by a browser share the selected telescopes, the displayed events and the selected
pixels (the client id `?c=...` of the links): going from a page to another keeps the context.

The viewer only reads and shows the data, as defined in the ctapipe / sst1mpipe containers: the
cameras show the values of a field (or of a sample of the waveforms), and every row received is
accumulated in the statistics (the selection of the events, e.g. cuts, belongs to the pipeline).

The telescopes are selected in the Selection page (or on the map of the Array page): every page shows the selected telescopes. A
click on a camera pixel selects it for its telescope on all the pages (shift+click adds or
removes a pixel); each telescope has its own selection. The displayed events are chosen in the
header:

- **Live**: the last event received, sampled every second (data pushed event by event, e.g. a stream);
- **◀ Prev** / **Next ▶**: the previous / next event of all the selected telescopes (◀ / ▶ next to
  a telescope name: of this telescope only);
- **Event id**: an `event_id`, or `#index` for the index of the event (`#0` the first, `#-1` the last).

**Valid levels.** A data level of an event is *valid* if (`sst1mpipe_viewer/validity.py`, the place
to change the rule): R0 / R1 / DL0 have a `waveform`; DL1 has Hillas parameters (finite
`hillas_intensity`); DL2 has at least one algorithm with `is_valid` true.

**Rates.** The rate of a level is the number of events whose level is valid, per minute, computed
from the timestamps of the events (trigger `time` or `event_time`; the events without timestamp
are not counted), with error bars for the statistical uncertainty (√N / duration). A dashed
vertical line marks the time of the displayed event of each telescope.

**Live sampling.** In Live mode the last event received of each telescope (and of the
subarray) is sampled every second, and all the pages show these same events until the next
sampling: the user has the time to look at them. The period is chosen in the header (1, 2, 5 or
10 s) or with `--live-period`. The events in between are not displayed, but they are all in the
statistics and the rates.

**Only valid levels are displayed.** A page shows the level of the displayed event only if it is
valid; otherwise a message says so (e.g. "No valid DL1 data in event N": the last event received
had no Hillas parameters, or no waveforms for the R0 page).

The cameras are drawn with pixels touching each other (the area of their grid cell, from the pitch
of the pixels, instead of their sensitive area which leaves gaps), and no plot can be moved
(no pan): the cameras and waveforms have only a box zoom in their toolbar, the other plots also
a wheel zoom.

The look follows the SST-1M web site (https://sst1m.space): black background, Roboto text and
Poppins titles (loaded from Google Fonts by the browser), the logos of the institutes of the
collaboration at the bottom of the pages (`sst1mpipe_viewer/style.py`). The Hillas ellipse is
drawn at 3 sigma.

The color maps are not chosen in the pages (lighter pages) but on the command line: `--colormap`
(waveform and image cameras), `--field-colormap` (per-pixel fields), `--color-scale lin|log`.

## Installation

```
pip install .
```

in an environment with ctapipe 0.32 (e.g. the sst1mpipe environment).

## Usage

The data come from **streams**, in one of two modes:

- **mono mode**: one stream per telescope, `--tel1` for the first telescope of the subarray
  (TEL 21) and `--tel2` for the second (TEL 22). Only the data of the telescope are read from its
  files, and no stereo data: the DL2 Stereo page stays empty.
- **stereo mode**: `--stereo`, one stream of complete array events: the data of all the
  telescopes and the stereo DL2 are read.

The two modes cannot be mixed (the events of the telescopes would be counted twice): the viewer
refuses to start with `--stereo` and `--tel1` / `--tel2`. Each option takes one or several files:
ctapipe HDF5 files (of `ctapipe-process` or sst1mpipe), DL3 FITS files (a DL3 given to `--tel1` is
the mono analysis of this telescope, to `--stereo` the stereo analysis), or files read by a ctapipe
`EventSource` (e.g. `run.simtel.gz`, processed event by event with the default ctapipe configuration).

```
sst1mpipe-viewer --tel1 tests/data/mrk421_tel21.h5 --tel2 tests/data/mrk421_tel22.h5
```

shows the files: all their events are processed at once (the statistics are those of all the
events) and the first event of each telescope is shown; any event can then be reached with Prev /
Next or its event id. The Mrk 421 test files (`tests/data/README.md`; `git lfs pull` to get them)
have the R0, R1, DL0 and DL1 data of the two SST-1M telescopes processed by sst1mpipe, one file
per telescope, and a file of emulated array events for the stereo mode; their DL2 and DL3
hold **random values** (the pipeline does not produce them yet).

```
sst1mpipe-viewer --tel1 tests/data/mrk421_tel21.h5 --tel2 tests/data/mrk421_tel22.h5 --replay-speed 1 --loop
```

replays the events as live streams, in the order and at the pace of their timestamps (`1`: real
time, `10`: ten times faster): the streams share a clock and stay synchronous, the displays follow
the last events and the statistics are accumulated. With `--loop` the files are replayed endlessly,
their timestamps being shifted at each pass so that the time keeps increasing. `--replay-rate HZ`
replays at a fixed rate instead (e.g. 1000 for a load test).

```
sst1mpipe-viewer --stereo tests/data/mrk421_stereo.h5 --replay-speed 1
```

replays array events: all the fields of an event are updated together (telescopes and stereo).

### Live stream of the pipeline (ZMQ)

The pipeline publishes the events it processes (`sst1mpipe-process --publish`, see
`sst1mpipe.io.zmq_event_stream` of sst1mpipe, which is then needed): the viewer **binds** an
endpoint per stream and the processes of the pipeline **connect** to it (PUB / SUB: several
processes can publish to the same stream, the pipeline never waits for the viewer).

```
sst1mpipe-viewer --tel1 tcp://*:5561 --tel2 tcp://*:5562                 # mono mode
sst1mpipe-process -i tcp://camera-21:24593 ... --publish tcp://viewer-host:5561
sst1mpipe-process -i tcp://camera-22:24593 ... --publish tcp://viewer-host:5562

sst1mpipe-viewer --stereo tcp://*:5563                                   # stereo mode
```

Without `-o`, `sst1mpipe-process` writes nothing to disk: the events are only processed and
published.

The full events (waveforms, images) are sent every second by the pipeline, the other events with
their trigger, DL1 parameters and DL2 (the statistics and the rates have all the events). To test
the viewer without the pipeline, `sst1mpipe-viewer-publish` publishes a file as the pipeline
would:

```
sst1mpipe-viewer --tel1 tcp://*:5561 --tel2 tcp://*:5562
sst1mpipe-viewer-publish tests/data/mrk421_tel21.h5 --url tcp://localhost:5561 --speed 1 --loop
sst1mpipe-viewer-publish tests/data/mrk421_tel22.h5 --url tcp://localhost:5562 --speed 1 --loop
```

The subarray (camera geometries, positions and Earth location of the telescopes) is read from
`--subarray FILE.h5`, by default the SST-1M subarray of sst1mpipe (`sst1m_array.h5`); the
telescopes of the files which are not in it are added.

The viewer is at http://localhost:5006/ (`--port`, `--allow-websocket-origin host:port` to reach
it from another machine). `sst1mpipe-viewer --help` lists the options (subarray, statistics
configuration, refresh periods).

### Reset of the plots

A single **Reset all plots** button, in the header of every page, resets every plot of the viewer
for everyone: the statistics of all the data levels and telescopes, the rates in time and the DL3
data. The events stay displayed.

The plots are also reset automatically **at sunset** at the site, so that a new night starts with
empty plots. The sunset is computed with astropy from the system time, at the reference location
of the subarray (the SST-1M site without subarray). `--sunset-reset auto` (default) does it with
a live stream (ZMQ endpoint) only, `on` always, `off` never. The status line shows the time of
the next reset.

In Live mode, a camera keeps the event it shows until another one can be displayed: it is never
emptied in between.

## Input of the viewer

The viewer displays the data pushed to a `ViewerStore`, from any thread:

```python
from sst1mpipe_viewer import ViewerStore, serve

store = ViewerStore(subarray)            # ctapipe SubarrayDescription: camera geometries, positions

# event by event (e.g. a stream): the last events are kept for the display
store.push_event(event)                  # ctapipe ArrayEventContainer: R0, R1, DL0, DL1, DL2 (tel and stereo), trigger
store.push_container("dl1", event.dl1.tel[1], obs_id=obs_id, event_id=event_id, tel_id=1)
store.push_row("dl1", row)               # dict or astropy table row

# a bunch of events (e.g. a file): processed at once, every event can be displayed
store.push_table("dl1", table)           # astropy table, e.g. /dl1/event/telescope/parameters/tel_001

serve(store, port=5006)                  # blocking: push the data from another thread
```

The kinds of data are `r0`, `r1`, `dl0`, `dl1`, `dl2`, `dl2_stereo` and `trigger`. The columns are those of the
ctapipe HDF5 tables: a container is flattened as by the ctapipe `DataWriter` (its fields keep their
name, the fields of its sub-containers take their prefix: `image`, `peak_time`, `image_mask`,
`hillas_intensity`, `leakage_intensity_width_2`, ...). Every row needs `obs_id`, `event_id` and
`tel_id`; the rows of the same event of a telescope are merged (e.g. a DL1 image row and a DL1
parameter row). The statistics are filled with the `dl1` and `dl2` rows (`store.statistics(tel_id,
"dl2")`). The DL1 parameters in the camera
frame written by sst1mpipe (`camera_frame_hillas_*`, in m) are converted to the telescope frame
(`hillas_fov_lon`, `hillas_length`, ... in deg) with the camera geometry of the subarray.

### DL2

The DL2 are those of the ctapipe `DL2Container` (as in the `SST1MArrayEventContainer`):
`event.dl2.tel[tel_id]` per telescope (kind `dl2`) and `event.dl2.stereo` for the subarray (kind
`dl2_stereo`, stored as the events of the pseudo telescope `SUBARRAY_ID = 0`). The columns are
those of the ctapipe tables, prefixed by the algorithm: `<algorithm>_tel_<field>` per telescope
(`/dl2/event/telescope/<group>/<algorithm>/tel_XXX`) and `<algorithm>_<field>` in stereo
(`/dl2/event/subarray/<group>/<algorithm>`).

The quantities are grouped as in the container (`sst1mpipe_viewer.dl2`): **geometry** (`alt`, `az`,
`core_x`, `core_y`, `h_max`, ... and their uncertainties), **energy** (`energy`, `energy_uncert`),
**classification** (`prediction`), and per telescope **impact** (`impact_distance`) and **disp**
(`disp_parameter`, `disp_sign_score`), plus `is_valid` and `goodness_of_fit`. The statistics are
accumulated for every combination of one algorithm per group; the menus of the pages choose which
one is shown. The quantities which are not plotted (uncertainties, goodness of fit, telescopes
used, ...) are in the table of the fields of the displayed event. The DL2 tables of sst1mpipe
(`reco_energy`, `gammaness`, `reco_alt`, `reco_az`) are shown as an algorithm called `sst1mpipe`.

The pipeline does not produce DL2 yet: to try the DL2 pages, `scripts/make_synthetic_dl2.py`
writes a copy of a DL1 file with **random** DL2 values in the ctapipe format (telescope and stereo):

```
python scripts/make_synthetic_dl2.py my_dl1_file.h5 /tmp/synthetic_dl2.h5
sst1mpipe-viewer --stereo /tmp/synthetic_dl2.h5
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

Measured on the server with the Mrk 421 files of the two telescopes, replayed at 1 kHz each
(2000 events/s in total):

| | files at once | 2 streams at 1 kHz |
|---|---|---|
| opening a page (building its document) | 0.2–0.6 s | 0.2–1.0 s |
| refresh of an event page (median) | 6–8 ms | 8–16 ms |
| refresh of a statistics page (median) | 1 ms | 13–23 ms |

Pushing a row takes about 40 µs (130 µs per event with all its levels), i.e. about a quarter of a
CPU core at 2000 events/s; the rate is held at 95 % while pages are being opened. The feed
threads and the bokeh server share the Python interpreter (GIL): a refresh can occasionally take
100–300 ms. Running the ingest (reading the streams, filling the statistics) in a separate
process would remove this contention.



### DL3

A DL3 event list is read at once, from a FITS file given on the command line (GADF format, as
written by `sst1mpipe_data_dl2_dl3`) or from the HDF5 file of a stream (table `/dl3/events`,
`sst1mpipe_viewer.dl3.write_dl3_hdf5`). The DL3 are accumulated per *series*: one per telescope in mono mode (two
superimposed histograms, one map per telescope), a single one in stereo mode. From Python:

```python
from sst1mpipe_viewer.dl3 import read_dl3

store.dl3.push(*read_dl3("dl3_file.fits"))             # stereo analysis
store.dl3.push(*read_dl3("dl3_tel21.fits"), series=21)  # mono analysis of TEL 21
```

The columns are those of the `EVENTS` table (`TIME`, `RA`, `DEC`, `ENERGY`, `DETX`, `DETY`). The
only values computed by the viewer are the positions of the events relative to the target of their
observation (`RA_OBJ` / `DEC_OBJ` of the header, the pointing if missing): `offset_lon`,
`offset_lat` and `theta2`, once when the events are pushed. To try the page without DL3 data,
`scripts/make_synthetic_dl3.py` writes a file of **random** events:

```
python scripts/make_synthetic_dl3.py /tmp/synthetic_dl3.fits
sst1mpipe-viewer --stereo /tmp/synthetic_dl3.fits
```

## Statistics configuration

The accumulated statistics of each data level are defined in a YAML file (defaults:
`src/sst1mpipe_viewer/resources/dl1_statistics.yaml`, `dl2_statistics.yaml`,
`dl2_stereo_statistics.yaml` and `dl3_statistics.yaml`; `--statistics-config`,
`--dl2-statistics-config`, `--dl2-stereo-statistics-config` and `--dl3-statistics-config` to use
others):

```yaml
hist1d:
  - {column: hillas_intensity, log_x: true, range: [1, 100000], bins: 50, log_y: true}
  - {column: hillas_width, range: [0, 0.4], bins: 50, unit: deg}
hist2d:
  - {x: hillas_intensity, x_log: true, x_range: [10, 100000], x_bins: 40, y: hillas_length, y_range: [0, 1], y_bins: 40}
```

A `display` section holds the options of the page of the level: for the DL2 Stereo page,
`ground_radius` (m, default 500) is the half size of the fixed view of the reconstructed core on
the ground, centred between the telescopes.

`log_x: true` gives logarithmic bins (of the values themselves, in `range`) drawn on a logarithmic
axis; `x_log` / `y_log` do the same for the axes of a 2D histogram, and `log_y` is the logarithmic
axis of the entries. (`transform: log10` is still available to histogram the logarithm of a column.)

## Code organisation

| Module | Role |
|---|---|
| `store.py` | `ViewerStore`: the data received (events, tables) and the accumulated statistics; the input of the viewer |
| `normalize.py` | Conversion of the inputs (containers, rows, tables) to columns `{name: numpy array}` |
| `accumulators.py`, `config.py` | Histograms and their YAML configuration |
| `frames.py`, `units.py` | Camera → telescope frame of the sst1mpipe parameters, display units |
| `dl2.py` | DL2: algorithms, groups of quantities and generic field names of the ctapipe `DL2Container` |
| `rates.py` | Rates per minute with their statistical uncertainties |
| `dl3.py` | DL3 event lists: reading of the FITS files, accumulated histograms, offsets to the target |
| `sunset.py` | Time of the next sunset at the site (astropy, system time) and automatic reset of the plots |
| `feeds.py`, `publish.py` | Reading of files (HDF5 tables, ctapipe `EventSource`) and of the ZMQ stream of the pipeline into a store; publishing a file as the pipeline (test tool) |
| `app.py`, `server.py`, `cli.py` | Bokeh pages (header, navigation, state shared by the pages of a browser), server, command line |
| `pages/` | One module per kind of page: `array.py`, `waveforms.py` (+ `trigger.py`), `events.py` (DL1 / DL2), `statistics.py`, `stereo.py` (DL2 Stereo), `dl3.py`, `pixel_selection.py` |
| `components/` | Bokeh displays independent of the store: camera, waveforms, histograms, rates, array map, fields table |
| `pixel_groups.py`, `colors.py`, `style.py` | DigiCam pixel groups (from CTS), colors of the telescopes, look of the pages |

## Tests

```
pip install .[test]
pytest
ruff check .
```
