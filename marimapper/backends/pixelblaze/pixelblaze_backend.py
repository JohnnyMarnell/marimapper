from multiprocessing import get_logger
import time
import socket
import json
import base64
from pathlib import Path

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
                    raise RuntimeError("No PixelBlazes found on network")

        logger.info(f"PixelBlaze server: {pixelblaze_ip}")

        try:
            ip_address(pixelblaze_ip)
        except ValueError:
            raise RuntimeError(
                f"Pixelblaze backend failed to start due as {pixelblaze_ip} is not a valid IP address"
            )

        try:
            logger.info(f"Connecting to PixelBlaze at {pixelblaze_ip}...")
            self.pb = pixelblaze.Pixelblaze(pixelblaze_ip)
        except ConnectionResetError:
            logger.error("\n\n")
            logger.error(f"❌ Connection refused by PixelBlaze at {pixelblaze_ip}")
            logger.error("❌ PixelBlaze may be unresponsive - try restarting it")
            logger.error("\n\n")
            raise RuntimeError(f"PixelBlaze at {pixelblaze_ip} refused connection")
        except Exception as e:
            logger.error("\n\n")
            logger.error(f"❌ Failed to connect to PixelBlaze: {e}")
            logger.error("\n\n")
            raise RuntimeError(f"Failed to connect to PixelBlaze: {e}")

        # logger.info("Checking PixelBlaze health...")
        # if not self._check_health():
        #     raise RuntimeError("\n\n\n**** ❌ Pattern not found, upload this repo's marimapper.epe to your PixelBlaze in its UI\n\n\n")

        self.set_mapper_pattern()

    def _check_health(self):
        try:
            patterns = self.pb.getPatternList()
            logger.info(f"Found {len(patterns)} pattern(s) on PixelBlaze")

            for _, pattern_name in patterns.items():
                if pattern_name.lower() == "marimapper":
                    logger.info("Marimapper pattern found")
                    return True

            logger.error("Marimapper pattern not found in pattern list")
            return False
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

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

    def set_mapper_pattern(self):
        with open(Path(__file__).parent / "marimapper.js", 'r', encoding='utf-8-sig') as f:
            source_code = f.read()
        bytecode = self.pb.compilePattern(source_code)
        self.pb.sendPatternToRenderer(bytecode)
    
    def upload_pattern(self):
            epe_path = Path(__file__).parent / "marimapper.epe"

            with open(epe_path, 'r', encoding='utf-8-sig') as f:
                epe_data = f.read()

            logger.info("Loading EPE file...")
            epe = pixelblaze.EPE.fromBytes(epe_data.encode('utf-8'))
            source_code = epe.sourceCode
            preview_image_b64 = epe.previewImage
            preview_image = base64.b64decode(preview_image_b64) if isinstance(preview_image_b64, str) else preview_image_b64

            logger.info("Compiling pattern...")
            bytecode = self.pb.compilePattern(source_code)
            logger.info("Compilation complete")

            sources_json = json.dumps({"main": source_code})

            logger.info("Saving pattern to PixelBlaze...")
            self.pb.savePattern(previewImage=preview_image, sourceCode=sources_json, byteCode=bytecode)
            logger.info("Pattern uploaded successfully")
