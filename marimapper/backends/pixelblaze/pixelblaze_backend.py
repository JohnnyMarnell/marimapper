from marimapper import logging
import pixelblaze


class Backend:

    def __init__(self, pixelblaze_ip="4.3.2.1"):
        self.pb = pixelblaze.Pixelblaze(pixelblaze_ip)

        pattern = [
            (pid, name)
            for pid, name in self.pb.getPatternList().items()
            if "marimapper" in name
        ]

        assert len(pattern) == 1, "marimapper pattern not found on Pixelblaze"

        self.pb.setActivePatternByName(
            "marimapper"
        )  # Need to install marimapper.js to your pixelblaze

        assert (
            self.pb.getActivePattern() == pattern[0][0]
        ), "Pixelblaze failed to set pattern"
        logging.info("Pixelblaze is running marimapper pattern")

    def get_led_count(self):
        pixel_count = self.pb.getPixelCount()
        logging.info(f"Pixelblaze reports {pixel_count} pixels")
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
