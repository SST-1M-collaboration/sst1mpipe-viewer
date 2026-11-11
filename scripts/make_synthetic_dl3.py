"""
Write a SYNTHETIC DL3 file (GADF event list, as ``sst1mpipe_data_dl2_dl3`` writes them) to try the
DL3 page of the viewer before the pipeline produces DL3 data.

The events are random (not reconstructed): a uniform background around the pointing and an excess
at the position of the target (Mrk 421), observed in wobble mode (pointing 0.7 deg from the target).

Usage::

    python scripts/make_synthetic_dl3.py /tmp/synthetic_dl3.fits
    sst1mpipe-viewer --stereo /tmp/synthetic_dl3.fits

or, to add the event list to the HDF5 file of a stream (read with its other data levels)::

    python scripts/make_synthetic_dl3.py my_stream.h5 --hdf5
"""

import argparse

import astropy.units as u
import numpy as np
from astropy.io import fits
from astropy.table import Table

#: Mrk 421 (deg)
TARGET_RA, TARGET_DEC = 166.1138, 38.2088


def synthetic_events(rng, n_background=4000, n_signal=400, obs_id=1, start=1768964778.0, livetime=1200.0):
    """EVENTS table of a synthetic observation (random values, see the module)"""
    pointing_ra, pointing_dec = TARGET_RA, TARGET_DEC + 0.7  # wobble
    # background: gaussian acceptance around the pointing; signal: point source smeared by the PSF
    detx = np.concatenate([rng.normal(0.0, 1.5, n_background), rng.normal(-0.7, 0.15, n_signal)])
    dety = np.concatenate([rng.normal(0.0, 1.5, n_background), rng.normal(0.0, 0.15, n_signal)])
    n = len(detx)
    events = Table()
    events["EVENT_ID"] = np.arange(n)
    events["TIME"] = np.sort(rng.uniform(start, start + livetime, n)) * u.s
    events["RA"] = (pointing_ra + dety / np.cos(np.deg2rad(pointing_dec))) * u.deg
    events["DEC"] = (pointing_dec + detx) * u.deg
    events["ENERGY"] = (10 ** rng.normal(0.3, 0.5, n)) * u.TeV
    events["DETX"] = detx * u.deg
    events["DETY"] = dety * u.deg
    order = rng.permutation(n)
    for name in ("RA", "DEC", "ENERGY", "DETX", "DETY"):
        events[name] = events[name][order]
    header = dict(OBS_ID=obs_id, OBJECT="Mrk 421 (synthetic)", RA_OBJ=TARGET_RA, DEC_OBJ=TARGET_DEC,
                  RA_PNT=pointing_ra, DEC_PNT=pointing_dec, LIVETIME=livetime, TSTART=start,
                  TSTOP=start + livetime, MJDREFI=40587, MJDREFF=0, TIMEUNIT="s", TELESCOP="SST-1M")
    return events, header


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", help="synthetic DL3 FITS file, or with --hdf5 the HDF5 file completed")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hdf5", action="store_true",
                        help="add the event list to an existing HDF5 file of a stream (table /dl3/events)"
                        " instead of writing a FITS file")
    args = parser.parse_args()
    events, header = synthetic_events(np.random.default_rng(args.seed))
    if args.hdf5:
        from sst1mpipe_viewer.dl3 import write_dl3_hdf5

        header["SYNTHETIC"] = "Random events (scripts/make_synthetic_dl3.py): NOT reconstructed data"
        write_dl3_hdf5(args.output, events, header)
        print(f"{args.output}: {len(events)} synthetic DL3 events in /dl3/events")
        return
    hdu = fits.BinTableHDU(events, name="EVENTS")
    hdu.header.update(header)
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(args.output, overwrite=True)
    print(f"{args.output}: {len(events)} synthetic DL3 events")


if __name__ == "__main__":
    main()
