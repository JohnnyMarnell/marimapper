from multiprocessing import get_logger
import time
import sys
import os
import socket

# see https://github.com/TheMariday/marimapper/issues/78
# why this is a UserWarning and not a DepreciationWarning is beyond me...
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, module="py_mini_racer")
    import pixelblaze

from ipaddress import ip_address
from functools import partial
import argparse

logger = get_logger()


def check_pixelblaze_reachable(ip, timeout=0.5):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, 81))
        sock.close()
        return result == 0
    except:
        return False


def discover_pixelblazes(timeout=3.0):
    logger.info(f"Listening for PixelBlaze beacon packets ({timeout}s)...")

    enumerator = pixelblaze.PixelblazeEnumerator()

    time.sleep(timeout)
    devices = enumerator.getPixelblazeList()
    enumerator.stop()

    logger.info(f"Found {len(devices)} PixelBlaze(s)")
    return devices


def pixelblaze_backend_factory(argparse_args: argparse.Namespace):
    return partial(Backend, argparse_args.server)


def pixelblaze_backend_set_args(parser):
    parser.add_argument(
        "--server",
        default="auto",
        help='IP address of PixelBlaze (default: "auto" - discovers first PixelBlaze on network)'
    )


class Backend:

    def __init__(self, pixelblaze_ip: str):
        # Handle auto-discovery mode
        if pixelblaze_ip.lower() == "auto":
            logger.info("Auto-discovering PixelBlaze...")

            # First check Ad Hoc mode (fast)
            logger.info("Checking for Ad Hoc mode (192.168.4.1)...")
            if check_pixelblaze_reachable("192.168.4.1"):
                pixelblaze_ip = "192.168.4.1"
                logger.info("Found PixelBlaze in Ad Hoc mode at 192.168.4.1")
            else:
                # Try beacon scan on network
                devices = discover_pixelblazes(timeout=3.0)
                if devices:
                    first_device = devices[0]
                    pixelblaze_ip = first_device.get('address') if isinstance(first_device, dict) else str(first_device)
                    logger.info(f"Found PixelBlaze at {pixelblaze_ip}")
                else:
                    logger.error("No PixelBlazes found. Specify IP with --server")
                    sys.exit(1)

        logger.info(f"PixelBlaze server: {pixelblaze_ip}")

        try:
            ip_address(pixelblaze_ip)
        except ValueError:
            raise RuntimeError(
                f"Pixelblaze backend failed to start due as {pixelblaze_ip} is not a valid IP address"
            )

        self.pb = pixelblaze.Pixelblaze(pixelblaze_ip)
        try:
            self.pb.setActivePatternByName(
                "marimapper"
            )  # Need to install marimapper.js to your pixelblaze
        except TypeError as e:
            if "'NoneType' has no len()" in str(e):
                raise RuntimeError(
                    "Pixelblaze may have failed to find the effect 'marimapper'. "
                    "Have you uploaded marimapper.epe to your controller?"
                )
            else:
                raise e

    def get_led_count(self):
        pixel_count = self.pb.getPixelCount()
        logger.info(f"Pixelblaze reports {pixel_count} pixels")
        return pixel_count

    def set_led(self, led_index: int, on: bool):
        self.pb.setActiveVariables({"pixel_to_light": led_index, "turn_on": on})

    def set_map_coordinates(self, pixelmap: list):
        result = self.pb.setMapCoordinates(pixelmap)
        if result is False:
            raise RuntimeError("Pixelblaze Backend failed to upload map coordinates.")
        self.pb.wsSendJson({"mapperFit": 0})

    def set_current_map(self, pixelmap_name: str):
        self.pb.setActivePatternByName(pixelmap_name)
