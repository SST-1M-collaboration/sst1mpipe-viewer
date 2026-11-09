"""
Write a copy of a DL1 file of sst1mpipe with a SYNTHETIC DL2 table, to try the DL2 pages of the
viewer before the pipeline produces DL2 data.

The DL2 values are random (not reconstructed): ``/dl2/event/telescope/parameters/tel_XXX`` with
the columns of sst1mpipe, ``reco_energy`` (TeV), ``gammaness``, ``reco_alt``, ``reco_az`` (deg),
``reco_src_x``, ``reco_src_y``, ``reco_disp_norm`` (m, camera frame), and the DL1 parameters.

Usage::

    python scripts/make_synthetic_dl2.py tests/data/mrk421_tel21_tel22.h5 /tmp/synthetic_dl2.h5
    sst1mpipe-viewer /tmp/synthetic_dl2.h5
"""

import argparse
import shutil

import numpy as np
import tables
from ctapipe.io import read_table, write_table


def synthetic_dl2(dl1, rng):
    """DL2 table of a DL1 parameter table of sst1mpipe (random values, see the module)"""
    n = len(dl1)
    dl2 = dl1.copy()
    intensity = np.nan_to_num(np.asarray(dl1["camera_frame_hillas_intensity"], dtype=float), nan=1.0)
    # energy roughly growing with the intensity, gammaness and direction at random
    dl2["reco_energy"] = np.clip(intensity, 1.0, None) / 300.0 * rng.lognormal(0.0, 0.3, n)
    dl2["gammaness"] = rng.beta(0.6, 0.6, n)
    psi = np.deg2rad(np.nan_to_num(np.asarray(dl1["camera_frame_hillas_psi"], dtype=float)))
    disp = rng.uniform(0.02, 0.3, n)
    sign = rng.choice([-1.0, 1.0], n)
    x = np.nan_to_num(np.asarray(dl1["camera_frame_hillas_x"], dtype=float))
    y = np.nan_to_num(np.asarray(dl1["camera_frame_hillas_y"], dtype=float))
    dl2["reco_disp_norm"] = disp
    dl2["reco_src_x"] = x + sign * disp * np.cos(psi)
    dl2["reco_src_y"] = y + sign * disp * np.sin(psi)
    dl2["reco_alt"] = 70.0 + rng.normal(0.0, 1.0, n)
    dl2["reco_az"] = 180.0 + rng.normal(0.0, 2.0, n)
    # the events without parameters (no pixel after the cleaning) are not reconstructed
    not_reconstructed = ~np.isfinite(np.asarray(dl1["camera_frame_hillas_intensity"], dtype=float))
    for name in ("reco_energy", "gammaness", "reco_disp_norm", "reco_src_x", "reco_src_y", "reco_alt", "reco_az"):
        dl2[name][not_reconstructed] = np.nan
    return dl2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="DL1 file of sst1mpipe")
    parser.add_argument("output", help="copy of the file with a synthetic DL2 table")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    shutil.copyfile(args.input, args.output)
    rng = np.random.default_rng(args.seed)
    with tables.open_file(args.input) as f:
        paths = [node._v_pathname for node in f.walk_nodes("/dl1/event/telescope/parameters", "Table")]
    for path in paths:
        name = path.rsplit("/", 1)[1]
        dl2 = synthetic_dl2(read_table(args.input, path), rng)
        write_table(dl2, args.output, f"/dl2/event/telescope/parameters/{name}", overwrite=True)
        print(f"{name}: {len(dl2)} synthetic DL2 rows")


if __name__ == "__main__":
    main()
