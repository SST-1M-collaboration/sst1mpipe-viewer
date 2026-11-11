# Test data

Mrk 421 (wobble W1, 2026-01-21) observed by the two SST-1M telescopes, processed by sst1mpipe from
the zfits test files of sst1mpipe (`sst1mpipe/resources/test_data/zfits`), as the streams of the
viewer (Git LFS):

| File | Stream | Content |
|---|---|---|
| `mrk421_tel21.h5` (32 MB) | mono, `--tel1` | TEL 21, run `SST1M1_20260120_1179.fits.fz`: DL1 and DL2 of the first 1000 events, R0 / R1 / DL0 waveforms of the first 50 |
| `mrk421_tel22.h5` (8 MB) | mono, `--tel2` | TEL 22, run `SST1M2_20260120_1102.fits.fz`: all the levels of its 22 events |
| `mrk421_stereo.h5` (22 MB) | stereo, `--stereo` | 22 **emulated** array events: all the levels of both telescopes and a stereo DL2 |

What is real and what is not:

- **R0, R1, DL0, DL1 are real data** processed by sst1mpipe.
- **The DL2 are SYNTHETIC**: the pipeline does not produce DL2 yet, so the DL2 tables hold **random
  values, not reconstructed data** (`scripts/make_synthetic_dl2.py --seed 421`), in the ctapipe
  format: per telescope (`/dl2/event/telescope/{geometry,impact,energy,classification,disp}/<algorithm>/tel_XXX`)
  and, in the stereo file, `/dl2/event/subarray/{geometry,energy,classification}/<algorithm>`.
- **The array events of the stereo file are EMULATED**: the two telescopes did not observe the same
  showers in these runs, so the i-th event of TEL 22 is paired with the i-th event of TEL 21 and
  takes its `obs_id`, `event_id` and time; a subarray trigger is written for these events.
- The groups concerned carry a `SYNTHETIC` attribute saying so.

- **The DL3 are SYNTHETIC**: each file has a DL3 event list of **random events** (table
  `/dl3/events` with the GADF columns, its header in the attributes `HEADER_*`; a uniform background
  and an excess at the position of Mrk 421), written by `scripts/make_synthetic_dl3.py --hdf5` with
  the seeds 21, 22 and 0: the mono analysis of the telescope in the telescope files, the stereo
  analysis in the stereo file. They are not derived from the Mrk 421 data.

- **R0**: the DigiCam raw data of sst1mpipe (`SST1MR0CameraContainer`): ADC waveforms, DigiCam
  baseline (`pedestal`), `pixel_flags`, trigger traces.
- **R1**: the waveforms calibrated by the `R0R1Calibrator` of sst1mpipe (p.e.).
- **DL0**: the waveforms after the data volume reduction of the `CameraCalibrator`. The data
  configuration of sst1mpipe has no data volume reduction, so that they are the R1 waveforms.
- **DL1**: images (`image`, `peak_time`, `image_mask`) and parameters, with the Hillas and timing
  parameters in the camera frame (`camera_frame_hillas_*`) as written by sst1mpipe.

The files also have the pointing and the pedestal statistics of the monitoring overlapping the
events. The pedestal events are not in the files (they are not written by `sst1mpipe-process`).

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

The file of the two telescopes is completed with the synthetic DL2 and split into the files of
the streams:

```
python ../../scripts/make_synthetic_dl2.py mrk421_tel21_tel22.h5 mrk421_tel21_tel22_dl2.h5 --seed 421
python make_stream_test_files.py mrk421_tel21_tel22_dl2.h5 --output-dir .
python ../../scripts/make_synthetic_dl3.py mrk421_tel21.h5 --hdf5 --seed 21
python ../../scripts/make_synthetic_dl3.py mrk421_tel22.h5 --hdf5 --seed 22
python ../../scripts/make_synthetic_dl3.py mrk421_stereo.h5 --hdf5 --seed 0
```

## Usage

```
# mono mode: one stream per telescope
sst1mpipe-viewer --tel1 tests/data/mrk421_tel21.h5 --tel2 tests/data/mrk421_tel22.h5

# stereo mode: the array events, with the (synthetic) stereo DL2 and DL3
sst1mpipe-viewer --stereo tests/data/mrk421_stereo.h5
```
