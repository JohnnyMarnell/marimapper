import argparse
import sys

sys.path.append("./")

from lib.reconstructor import Reconstructor
from lib.utils import add_camera_args
from lib import logging

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Tests your webcam and LED detection algorithms"
    )

    add_camera_args(parser)

    args = parser.parse_args()

    if args.width * args.height < 0:
        logging.error(
            "Failed to start camera checker as both camera width and height need to be provided"
        )
        quit()

    reconstructor = Reconstructor(
        args.device,
        args.exposure,
        args.threshold,
        None,
        width=args.width,
        height=args.height,
    )

    logging.info(
        "Camera connected! Hold an LED up to the camera to check LED identification"
    )
    reconstructor.show_debug()
