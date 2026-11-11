"""
Write ``src/sst1mpipe_viewer/resources/digicam_pixel_groups.csv``: the groups of each pixel of the
DigiCam camera (trigger patch, module, FADC board, CAN node, sector), read from the camera
configuration of CTS (``sst1m-cts``), so that the viewer does not need CTS.

    python scripts/make_pixel_groups.py /path/to/sst1mpipe/resources/instrument/camera_config.cfg
"""

import argparse
import csv
from pathlib import Path

from sst1m_cts_core.camera import Camera

OUTPUT = Path(__file__).parents[1] / "src" / "sst1mpipe_viewer" / "resources" / "digicam_pixel_groups.csv"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("camera_config", type=Path, help="camera_config.cfg of the camera (e.g. of sst1mpipe)")
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    camera = Camera(_config_file=str(args.camera_config))
    with args.output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pixel", "patch", "module", "fadc_board", "can_node", "sector"])
        for pixel in sorted(camera.Pixels, key=lambda p: p.ID):
            # fadc_unique: sector * 16 + FADC board of the sector
            writer.writerow([pixel.ID, pixel.patch, pixel.module, pixel.fadc_unique, pixel.CANnode, pixel.sector])


if __name__ == "__main__":
    main()
