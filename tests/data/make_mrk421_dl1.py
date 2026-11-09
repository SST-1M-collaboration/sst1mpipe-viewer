"""
Build ``mrk421_tel21_tel22.dl1.h5``, the DL1 test file of the viewer: Mrk 421 events of the two
SST-1M telescopes processed by sst1mpipe (see README.md in this directory).

The two runs are processed separately by sst1mpipe (one telescope each), so that their output
files have different subarrays and cannot be merged by ``ctapipe-merge``. This script writes the
first ``--n-events`` events of each file in a single file with the subarray of both telescopes.
The monitoring chunks are those overlapping the kept events. The values are not modified, except
``tels_with_trigger`` of the subarray trigger table (the mask of the triggered telescopes is
rebuilt for the merged subarray).

    python make_mrk421_dl1.py SST1M1_20260120_1179.dl1.h5 SST1M2_20260120_1102.dl1.h5 \
        -o mrk421_tel21_tel22.dl1.h5 --n-events 1000
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
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--n-events", type=int, default=1000, help="first events kept per file")
    args = parser.parse_args(argv)

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
    for path, tel_id in zip(args.inputs, tel_ids):
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
