# Test data

`mrk421_tel21_tel22.h5` (Git LFS, 39 MB): Mrk 421 (wobble W1, 2026-01-21) observed by the two
SST-1M telescopes, processed by sst1mpipe from the zfits test files of sst1mpipe
(`sst1mpipe/resources/test_data/zfits`), at all the data levels:

| Telescope | Run | DL1 (images, parameters, triggers) | R0, R1, DL0 waveforms |
|---|---|---|---|
| TEL 1 (`tel_id` 21) | `SST1M1_20260120_1179.fits.fz` | the first 1000 events | the first 50 events |
| TEL 2 (`tel_id` 22) | `SST1M2_20260120_1102.fits.fz` | all the 22 events | all the 22 events |

- **R0**: the DigiCam raw data of sst1mpipe (`SST1MR0CameraContainer`): ADC waveforms, DigiCam
  baseline (`pedestal`), `pixel_flags`, trigger traces.
- **R1**: the waveforms calibrated by the `R0R1Calibrator` of sst1mpipe (p.e.).
- **DL0**: the waveforms after the data volume reduction of the `CameraCalibrator`. The data
  configuration of sst1mpipe has no data volume reduction, so that they are the R1 waveforms.
- **DL1**: images (`image`, `peak_time`, `image_mask`) and parameters, with the Hillas and timing
  parameters in the camera frame (`camera_frame_hillas_*`) as written by sst1mpipe.

- **DL2 (SYNTHETIC)**: the pipeline does not produce DL2 yet, so the DL2 tables of the file hold
  **random values, not reconstructed data**, written by `scripts/make_synthetic_dl2.py --seed 421`
  in the ctapipe format, to try and test the DL2 pages: per telescope
  (`/dl2/event/telescope/{geometry,impact,energy,classification,disp}/<algorithm>/tel_XXX`) and
  stereo (`/dl2/event/subarray/{geometry,energy,classification}/<algorithm>`, 22 events paired at
  random, with their subarray trigger `/dl1/event/subarray/trigger`). The groups `/dl2` and
  `/dl1/event/subarray` carry a `SYNTHETIC` attribute saying so.

`synthetic_dl3_tel21.fits`, `synthetic_dl3_tel22.fits` and `synthetic_dl3_stereo.fits` are DL3
event lists of **random events** (`scripts/make_synthetic_dl3.py`, seeds 21, 22 and 0; a uniform
background and an excess at the position of Mrk 421), to try and test the DL3 page in mono and
stereo modes. They are not derived from the Mrk 421 data.

The file also has the pointing and the pedestal statistics of the monitoring overlapping the
events. The pedestal events are not in the file (they are not written by `sst1mpipe-process`).

## How it was made

sst1mpipe `main` (9006128), ctapipe 0.32.0, Python 3.12, for each run:

```
sst1mpipe-monitoring --input=RUN.fits.fz --output=RUN.monitoring.h5 \
    --config=sst1mpipe/resources/config/sst1mpipe_monitoring_config.json

python sst1mpipe_process_with_dl0.py --input=RUN.fits.fz --output=RUN.dl1.h5 --dl0-output=RUN.dl0.h5 \
    --config=sst1mpipe/resources/config/sst1mpipe_data_config.json \
    --monitoring-source=SST1MMonitoringSource --SST1MMonitoringSource.input_files=RUN.monitoring.h5 \
    --ProcessorTool.wobble_in_output_name=False --DataWriter.write_dl1_images=True \
    --DataWriter.write_r0_waveforms=True --DataWriter.write_r1_waveforms=True \
    --EventSource.max_events=1400
```

`sst1mpipe_process_with_dl0.py` is `sst1mpipe-process` that also writes the DL0 waveforms (the
ctapipe 0.32 `DataWriter` does not write them). The two outputs (one telescope each, so that
`ctapipe-merge` cannot merge them) are then written in a single file by
`make_mrk421_test_file.py`:

```
python make_mrk421_test_file.py SST1M1_20260120_1179.dl1.h5 SST1M2_20260120_1102.dl1.h5 \
    --dl0 SST1M1_20260120_1179.dl0.h5 SST1M2_20260120_1102.dl0.h5 \
    -o mrk421_tel21_tel22.h5 --n-events 1000 --n-waveform-events 50
```

## Usage

```
# mono mode: one stream per telescope
sst1mpipe-viewer --tel1 tests/data/mrk421_tel21_tel22.h5 tests/data/synthetic_dl3_tel21.fits \
                 --tel2 tests/data/mrk421_tel21_tel22.h5 tests/data/synthetic_dl3_tel22.fits

# stereo mode: the array events, with the (synthetic) stereo DL2
sst1mpipe-viewer --stereo tests/data/mrk421_tel21_tel22.h5 tests/data/synthetic_dl3_stereo.fits
```
