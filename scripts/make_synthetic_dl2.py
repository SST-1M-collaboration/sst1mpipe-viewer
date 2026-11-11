"""
Write a copy of a DL1 file with SYNTHETIC DL2 tables in the ctapipe format, to try the DL2 pages
of the viewer before the pipeline produces DL2 data.

The DL2 values are random (not reconstructed). The tables are those written by the ctapipe
``DataWriter`` for a ``DL2Container``:

- per telescope, ``/dl2/event/telescope/<group>/<algorithm>/tel_XXX``: geometry
  (``HillasReconstructor``, with the impact), energy (``RandomForestRegressor``), classification
  (``RandomForestClassifier``) and disp (``DispReconstructor``);
- stereo, ``/dl2/event/subarray/<group>/<algorithm>``: geometry (``HillasReconstructor``), energy
  and classification, for the events seen by the two telescopes (here: paired at random), with
  the subarray trigger ``/dl1/event/subarray/trigger``.

Usage::

    python scripts/make_synthetic_dl2.py my_dl1_file.h5 /tmp/synthetic_dl2.h5
    sst1mpipe-viewer --stereo /tmp/synthetic_dl2.h5
"""

import argparse
import shutil

import numpy as np
import tables
from astropy.table import Table
from ctapipe.io import read_table, write_table

KEYS = ("obs_id", "event_id", "tel_id")
#: attribute written on the synthetic groups of the output file
SYNTHETIC_NOTE = "Random values written by sst1mpipe-viewer/scripts/make_synthetic_dl2.py: NOT reconstructed data"


def telescope_tables(dl1, rng):
    """``{(group, algorithm): table}`` of the DL2 of a telescope from its DL1 parameters (random values)"""
    n = len(dl1)
    intensity = np.asarray(dl1["camera_frame_hillas_intensity"], dtype=float)
    reconstructed = np.isfinite(intensity)  # the events without parameters are not reconstructed

    def table(**columns):
        result = Table({key: dl1[key] for key in KEYS})
        for name, values in columns.items():
            values = np.asarray(values, dtype=float)
            if not name.endswith("is_valid"):
                values = np.where(reconstructed, values, np.nan)
            result[name] = values if not name.endswith("is_valid") else reconstructed
        return result

    energy = np.clip(np.nan_to_num(intensity, nan=1.0), 1.0, None) / 300.0 * rng.lognormal(0.0, 0.3, n)
    return {
        ("geometry", "HillasReconstructor"): table(
            HillasReconstructor_tel_alt=70.0 + rng.normal(0.0, 1.0, n),
            HillasReconstructor_tel_alt_uncert=rng.uniform(0.05, 0.5, n),
            HillasReconstructor_tel_az=180.0 + rng.normal(0.0, 2.0, n),
            HillasReconstructor_tel_az_uncert=rng.uniform(0.05, 0.5, n),
            HillasReconstructor_tel_is_valid=reconstructed,
        ),
        ("impact", "HillasReconstructor"): table(
            HillasReconstructor_tel_impact_distance=rng.uniform(0.0, 400.0, n),
            HillasReconstructor_tel_impact_distance_uncert=rng.uniform(1.0, 30.0, n),
        ),
        ("energy", "RandomForestRegressor"): table(
            RandomForestRegressor_tel_energy=energy,
            RandomForestRegressor_tel_energy_uncert=0.2 * energy,
            RandomForestRegressor_tel_is_valid=reconstructed,
        ),
        ("classification", "RandomForestClassifier"): table(
            RandomForestClassifier_tel_prediction=rng.beta(0.6, 0.6, n),
            RandomForestClassifier_tel_is_valid=reconstructed,
        ),
        ("disp", "DispReconstructor"): table(
            DispReconstructor_tel_parameter=rng.normal(0.0, 1.0, n),
            DispReconstructor_tel_sign_score=rng.uniform(0.0, 1.0, n),
        ),
    }


def stereo_tables(obs_ids, event_ids, times, n_tels, rng):
    """``{(group, algorithm): table}`` of the stereo DL2 of events, and their subarray trigger table"""
    n = len(event_ids)

    def table(**columns):
        return Table(dict(obs_id=obs_ids, event_id=event_ids, **columns))

    used = np.ones((n, n_tels), dtype=bool)
    energy = 10 ** rng.normal(0.0, 0.5, n)
    result = {
        ("geometry", "HillasReconstructor"): table(
            HillasReconstructor_alt=70.0 + rng.normal(0.0, 0.5, n),
            HillasReconstructor_alt_uncert=rng.uniform(0.02, 0.2, n),
            HillasReconstructor_az=180.0 + rng.normal(0.0, 1.0, n),
            HillasReconstructor_az_uncert=rng.uniform(0.02, 0.2, n),
            HillasReconstructor_ang_distance_uncert=rng.uniform(0.02, 0.3, n),
            HillasReconstructor_core_x=rng.normal(0.0, 150.0, n),
            HillasReconstructor_core_y=rng.normal(0.0, 150.0, n),
            HillasReconstructor_h_max=rng.normal(9000.0, 2000.0, n),
            HillasReconstructor_average_intensity=10 ** rng.normal(2.3, 0.4, n),
            HillasReconstructor_is_valid=np.ones(n, dtype=bool),
            HillasReconstructor_telescopes=used,
        ),
        ("energy", "RandomForestRegressor"): table(
            RandomForestRegressor_energy=energy,
            RandomForestRegressor_energy_uncert=0.15 * energy,
            RandomForestRegressor_is_valid=np.ones(n, dtype=bool),
        ),
        ("classification", "RandomForestClassifier"): table(
            RandomForestClassifier_prediction=rng.beta(0.6, 0.6, n),
            RandomForestClassifier_is_valid=np.ones(n, dtype=bool),
        ),
    }
    trigger = table(time=times, tels_with_trigger=used)
    return result, trigger


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="DL1 file (ctapipe / sst1mpipe format)")
    parser.add_argument("output", help="copy of the file with synthetic DL2 tables")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    shutil.copyfile(args.input, args.output)
    rng = np.random.default_rng(args.seed)
    with tables.open_file(args.input) as f:
        paths = [node._v_pathname for node in f.walk_nodes("/dl1/event/telescope/parameters", "Table")]
    n_events = []
    for path in paths:
        name = path.rsplit("/", 1)[1]
        dl1 = read_table(args.input, path)
        n_events.append(len(dl1))
        for (group, algorithm), table in telescope_tables(dl1, rng).items():
            write_table(table, args.output, f"/dl2/event/telescope/{group}/{algorithm}/{name}", overwrite=True)
        print(f"{name}: {len(dl1)} synthetic telescope DL2 rows")

    # stereo: as many events as the telescope with the fewest events, with the ids and times of its events
    trigger = read_table(args.input, "/dl1/event/telescope/trigger")
    smallest = read_table(args.input, paths[int(np.argmin(n_events))])
    mask = trigger["tel_id"] == smallest["tel_id"][0]
    times = dict(zip(trigger["event_id"][mask].tolist(), trigger["time"][mask]))
    event_times = [times[i] for i in smallest["event_id"].tolist()]
    stereo, stereo_trigger = stereo_tables(np.asarray(smallest["obs_id"]), np.asarray(smallest["event_id"]),
                                           event_times, len(paths), rng)
    for (group, algorithm), table in stereo.items():
        write_table(table, args.output, f"/dl2/event/subarray/{group}/{algorithm}", overwrite=True)
    write_table(stereo_trigger, args.output, "/dl1/event/subarray/trigger", overwrite=True)
    print(f"subarray: {len(smallest)} synthetic stereo DL2 rows")
    # mark the DL2 of the file as synthetic
    with tables.open_file(args.output, "a") as f:
        f.root.dl2._v_attrs.SYNTHETIC = SYNTHETIC_NOTE
        f.root.dl1.event.subarray._v_attrs.SYNTHETIC = SYNTHETIC_NOTE


if __name__ == "__main__":
    main()
