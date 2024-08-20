import cv2
import time
import math
from threading import Thread

from marimapper.camera import Camera, CameraSettings
from marimapper.led_identifier import LedFinder
from marimapper import logging
from marimapper.timeout_controller import TimeoutController


class Reconstructor:

    def __init__(
        self,
        device,
        dark_exposure,
        threshold,
        led_backend,
        width=-1,
        height=-1,
        camera=None,
    ):
        self.settings_backup = None
        self.cam = Camera(device) if camera is None else camera
        self.settings_backup = CameraSettings(self.cam)
        self.led_backend = led_backend

        self.dark_exposure = dark_exposure
        self.light_exposure = self.cam.get_exposure()

        self.led_finder = LedFinder(threshold)
        self.timeout_controller = TimeoutController()

        if width != -1 and height != -1:
            self.cam.set_resolution(width, height)

        self.cam.set_autofocus(0, 0)
        self.cam.set_exposure_mode(0)
        self.cam.set_gain(0)

        self.live_feed = None
        self.live_feed_running = False

    def close(self):
        self.close_live_feed()
        cv2.destroyAllWindows()

        if self.settings_backup is not None:
            logging.debug("Reverting camera changes...")
            self.settings_backup.apply(self.cam)
            logging.debug("Camera changes reverted")

    def light(self):
        self.cam.set_exposure_and_wait(self.light_exposure)

    def dark(self):
        self.cam.set_exposure_and_wait(self.dark_exposure)

    def open_live_feed(self):
        cv2.destroyAllWindows()

        time.sleep(2)

        self.live_feed_running = True
        self.live_feed = Thread(target=self._live_thread_loop)
        self.live_feed.start()

    def close_live_feed(self):
        self.live_feed_running = False
        if self.live_feed is not None:
            if self.live_feed.is_alive():
                self.live_feed.join()

    def _live_thread_loop(self):

        # TODO(jmarnell) - clean up and remove my debug stuff
        print("temp sleep start")
        time.sleep(5)
        print("temp sleep done")

        while self.live_feed_running:

            if cv2.getWindowProperty("MariMapper", cv2.WND_PROP_VISIBLE) <= 0:
                self.live_feed_running = False

            image = self.cam.read(color=True)
            cv2.imshow("MariMapper", image)
            cv2.waitKey(1)

        cv2.destroyAllWindows()

    def create_window(self):
        # self.dark()
        cv2.namedWindow("MariMapper", cv2.WINDOW_AUTOSIZE)
        print("prop_viz", cv2.getWindowProperty("MariMapper", cv2.WND_PROP_VISIBLE))

    def show_debug(self):

        self.dark()

        cv2.namedWindow("MariMapper", cv2.WINDOW_AUTOSIZE)

        while True:

            if cv2.getWindowProperty("MariMapper", cv2.WND_PROP_VISIBLE) <= 0:
                break

            self.find_led(debug=True)

    def find_led(self, debug=False):

        image = self.cam.read()
        results = self.led_finder.find_led(image)

        if debug:
            rendered_image = self.led_finder.draw_results(image, results)
            cv2.imshow("MariMapper", rendered_image)
            key = cv2.waitKey(1)
            if key != -1:
                print("key", key)

        return results

    def enable_and_find_led(self, led_id, debug=False):

        # First wait for no leds to be visible
        print("Waiting for no leds to be visible")
        while self.find_led(debug) is not None:
            pass

        # Set the led to on and start the clock
        response_time_start = time.time()

        self.led_backend.set_led(led_id, True)

        # Wait until either we have a result or we run out of time
        result = None
        while (
            result is None
            and time.time() < response_time_start + self.timeout_controller.timeout
        ):
            result = self.find_led(debug)

        self.led_backend.set_led(led_id, False)

        if result is None:
            return None

        self.timeout_controller.add_response_time(time.time() - response_time_start)

        while self.find_led(debug) is not None:
            pass

        return result

    def get_camera_motion(self, valid_leds, map_data_2d):

        if len(valid_leds) == 0:
            return 0

        for led_id in valid_leds:
            detection_new = self.enable_and_find_led(led_id, debug=True)
            if detection_new:
                detection_orig = map_data_2d.get_detection(led_id)

                distance_between_first_and_last = math.hypot(
                    detection_orig.u - detection_new.u,
                    detection_orig.v - detection_new.v,
                )
                return distance_between_first_and_last * 100

        return 100
