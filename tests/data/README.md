# Test data

`mrk421_tel21_tel22.dl1.h5` (Git LFS): DL1 data of Mrk 421 (wobble W1, 2026-01-21) of the two
SST-1M telescopes, processed by sst1mpipe from the zfits test files of sst1mpipe
(`sst1mpipe/resources/test_data/zfits`):

| Telescope | Run | Events in the run | Events in the file |
|---|---|---|---|
| TEL 1 (`tel_id` 21) | `SST1M1_20260120_1179.fits.fz` | 3175 (+ pedestals) | the first 1000 |
| TEL 2 (`tel_id` 22) | `SST1M2_20260120_1102.fits.fz` | 22 (+ pedestals) | all |

The file has the DL1 images (`image`, `peak_time`, `image_mask`) and parameters of the events,
with the Hillas and timing parameters in the camera frame (`camera_frame_hillas_*`, as written by
sst1mpipe), the triggers, the pointing and the pedestal statistics of the monitoring overlapping
the events.

## How it was made

sst1mpipe `main` (9006128), ctapipe 0.32.0, Python 3.12, for each run:

```
sst1mpipe-monitoring --input=RUN.fits.fz --output=RUN.monitoring.h5 \
    --config=sst1mpipe/resources/config/sst1mpipe_monitoring_config.json

sst1mpipe-process --input=RUN.fits.fz --output=RUN.dl1.h5 \
    --config=sst1mpipe/resources/config/sst1mpipe_data_config.json \
    --monitoring-source=SST1MMonitoringSource --SST1MMonitoringSource.input_files=RUN.monitoring.h5 \
    --ProcessorTool.wobble_in_output_name=False --DataWriter.write_dl1_images=True
```

then the two output files (one telescope each, so that `ctapipe-merge` cannot merge them) are
written in a single file by `make_mrk421_dl1.py`:

```
python make_mrk421_dl1.py SST1M1_20260120_1179.dl1.h5 SST1M2_20260120_1102.dl1.h5 \
    -o mrk421_tel21_tel22.dl1.h5 --n-events 1000
```

## Usage

```
sst1mpipe-viewer --demo tests/data/mrk421_tel21_tel22.dl1.h5 --rate 5
```
