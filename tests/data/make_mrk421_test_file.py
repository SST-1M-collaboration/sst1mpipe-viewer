"""
Build ``mrk421_tel21_tel22.h5``, the test file of the viewer: Mrk 421 events of the two SST-1M
telescopes processed by sst1mpipe, at all the data levels (see README.md in this directory).

The two runs are processed separately by sst1mpipe (one telescope each), so that their output
files have different subarrays and cannot be merged by ``ctapipe-merge``. This script writes, in
a single file with the subarray of both telescopes, the DL1 data (images, parameters, triggers)
of the first ``--n-events`` events of each run and the R0, R1 and DL0 waveforms of the first
``--n-waveform-events`` of them. The DL0 waveforms are read from the ``--dl0`` files (one per
input, written by sst1mpipe_process_with_dl0.py). The monitoring chunks are those overlapping the
kept events. The values are not modified, except:

- ``tels_with_trigger`` of the subarray trigger table: the mask of the triggered telescopes is
  rebuilt for the merged subarray;
- the R1 and DL0 waveforms are stored in float32 (float64 in the sst1mpipe output), the dtype of
  the ctapipe containers, to halve the size of the file (relative difference < 1e-7).

    python make_mrk421_test_file.py SST1M1_20260120_1179.dl1.h5 SST1M2_20260120_1102.dl1.h5 \
        --dl0 SST1M1_20260120_1179.dl0.h5 SST1M2_20260120_1102.dl0.h5 \
        -o mrk421_tel21_tel22.h5 --n-events 1000 --n-waveform-events 50
"""

import argparse

import numpy as np
from astropy.table import vstack
from ctapipe.instrument import SubarrayDescription
from ctapipe.io import read_table, write_table

TELESCOPE_TABLES = (
    "/dl1/event/telescope/images/tel_{tel_id:03d}",
    "/dl1/event/telescope/parameters/tel_{tel_id:03d}",
    "/dl0/monitoring/telescope/pointing/tel_{tel_id:03d}",
    "/dl1/monitoring/telescope/calibration/camera/pixel_statistics/sky_pedestal_image/tel_{tel_id:03d}",
    "/r0/monitoring/telescope/calibration/camera/pixel_statistics/sky_pedestal_waveform/tel_{tel_id:03d}",
)
STACKED_TABLES = (
    "/configuration/observation/observation_block",
    "/configuration/observation/scheduling_block",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", help="DL1 files of sst1mpipe-process, one telescope each")
    parser.add_argument("--dl0", nargs="+", default=None, help="DL0 files of the inputs, in the same order")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--n-events", type=int, default=1000, help="first events kept per file")
    parser.add_argument("--n-waveform-events", type=int, default=50,
                        help="first events whose R0, R1 and DL0 waveforms are kept, per file")
    args = parser.parse_args(argv)
    if args.dl0 is not None and len(args.dl0) != len(args.inputs):
        parser.error("one --dl0 file per input file")

    subarrays = [SubarrayDescription.from_hdf(path) for path in args.inputs]
    tel_ids = [subarray.tel_ids[0] for subarray in subarrays]
    if any(len(subarray.tel_ids) != 1 for subarray in subarrays) or len(set(tel_ids)) != len(tel_ids):
        parser.error("each input file must have one telescope, a different one")
    reference = subarrays[0].reference_location
    subarray = SubarrayDescription(
        name=subarrays[0].name,
        tel_positions={t: s.positions[t] for t, s in zip(tel_ids, subarrays)},
        tel_descriptions={t: s.tel[t] for t, s in zip(tel_ids, subarrays)},
        reference_location=reference,
    )
    subarray.to_hdf(args.output, overwrite=True)

    triggers, stacked = [], {path: [] for path in STACKED_TABLES}
    for i, (path, tel_id) in enumerate(zip(args.inputs, tel_ids)):
        parameters = read_table(path, f"/dl1/event/telescope/parameters/tel_{tel_id:03d}")[:args.n_events]
        event_ids = set(zip(parameters["obs_id"], parameters["event_id"]))

        def kept(table):
            return np.array([(o, e) in event_ids for o, e in zip(table["obs_id"], table["event_id"])], dtype=bool)

        times = read_table(path, "/dl1/event/telescope/trigger")
        times = times[kept(times)]["time"]
        t_min, t_max = times.min(), times.max()

        for template in TELESCOPE_TABLES:
            table_path = template.format(tel_id=tel_id)
            table = read_table(path, table_path)
            if "event_id" in table.colnames:
                table = table[kept(table)]
            elif "time_start" in table.colnames:
                # chunks of monitoring data overlapping the kept events
                table = table[(table["time_start"] <= t_max) & (table["time_end"] >= t_min)]
            write_table(table, args.output, table_path, append=True)

        # waveforms of the first events
        waveform_ids = set(zip(parameters["obs_id"][:args.n_waveform_events],
                               parameters["event_id"][:args.n_waveform_events]))
        waveform_tables = [(path, f"/r0/event/telescope/tel_{tel_id:03d}"),
                           (path, f"/r1/event/telescope/tel_{tel_id:03d}")]
        if args.dl0 is not None:
            waveform_tables.append((args.dl0[i], f"/dl0/event/telescope/tel_{tel_id:03d}"))
        for source, table_path in waveform_tables:
            table = read_table(source, table_path)
            table = table[[(o, e) in waveform_ids for o, e in zip(table["obs_id"], table["event_id"])]]
            if not table_path.startswith("/r0") and table["waveform"].dtype == np.float64:
                table["waveform"] = table["waveform"].astype(np.float32)
            write_table(table, args.output, table_path, append=True)

        telescope_trigger = read_table(path, "/dl1/event/telescope/trigger")
        write_table(telescope_trigger[kept(telescope_trigger)], args.output, "/dl1/event/telescope/trigger",
                    append=True)

        trigger = read_table(path, "/dl1/event/subarray/trigger")
        trigger = trigger[kept(trigger)]
        mask = np.zeros((len(trigger), len(subarray)), dtype=bool)
        mask[:, subarray.tel_index_array[tel_id]] = True
        trigger["tels_with_trigger"] = mask
        triggers.append(trigger)

        for table_path in STACKED_TABLES:
            stacked[table_path].append(read_table(path, table_path))

    trigger = vstack(triggers)
    trigger.sort("time")
    write_table(trigger, args.output, "/dl1/event/subarray/trigger")
    for table_path, tables in stacked.items():
        write_table(vstack(tables), args.output, table_path)


if __name__ == "__main__":
    main()
