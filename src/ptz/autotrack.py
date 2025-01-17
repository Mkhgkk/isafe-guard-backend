from typing import List, Tuple, Optional, Dict, Union
from onvif import ONVIFCamera, exceptions
import time
import queue
import threading
import numpy as np
import sys


class PTZAutoTracker:
    def __init__(
        self, cam_ip: str, ptz_port: int, ptz_username: str, ptz_password: str
    ) -> None:
        self.camera: ONVIFCamera = ONVIFCamera(
            cam_ip, ptz_port, ptz_username, ptz_password
        )
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()

        if self.profiles is None:
            raise ValueError(
                "No profiles returned from the camera. Please check connection or credentials."
            )

        self.profile_token: str = self.profiles[0].token

        self.center_tolerance_x: float = 0.1
        self.center_tolerance_y: float = 0.1

        self.pan_velocity: float = 0.8
        self.tilt_velocity: float = 0.8
        self.zoom_velocity: float = 0.02

        self.min_zoom: float = 0.1
        self.max_zoom: float = 0.3

        self.last_move_time: float = time.time()
        self.move_throttle_time: float = 0.5

        self.no_object_timeout: float = 5
        self.last_detection_time: float = time.time()
        self.default_position: Dict[str, float] = {
            "pan": 0,
            "tilt": 0,
            "zoom": self.min_zoom,
        }
        self.is_moving: bool = False
        self.move_queue: queue.Queue[Tuple[float, float, float]] = queue.Queue()
        self.move_thread: threading.Thread = threading.Thread(
            target=self._process_move_queue
        )
        self.move_thread.start()

        self.is_at_default_position: bool = False

        self.ptz_metrics: Dict[str, float] = {
            "zoom_level": self.min_zoom,
        }
        self.calibrating: bool = False

        self.home_pan: float = 0
        self.home_tilt: float = 0
        self.home_zoom: float = self.min_zoom

    def update_default_position(self, pan: float, tilt: float, zoom: float) -> None:
        self.home_pan = pan
        self.home_tilt = tilt
        self.home_zoom = zoom

    def get_ptz_status(self) -> Optional[dict]:
        # get ptz status
        try:
            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            return status
        except exceptions.ONVIFError as e:
            print(f"Error getting PTZ status: {e}")
            return None

    def calculate_movement(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: List[Tuple[float, float, float, float]],
    ) -> Tuple[float, float, float]:
        # calculate the necessary pan, tilt, and zoom changed to keep the object in the center
        if not bboxes:
            return 0.0, 0.0, 0.0

        frame_center_x: float = frame_width / 2
        frame_center_y: float = frame_height / 2

        bbox_centers_x: List[float] = []
        bbox_centers_y: List[float] = []
        bbox_areas: List[float] = []

        for bbox in bboxes:
            x1, y1, x2, y2 = bbox

            bbox_width: float = x2 - x1
            bbox_height: float = y2 - y1
            bbox_center_x: float = x1 + bbox_width / 2
            bbox_center_y: float = y1 + bbox_height / 2

            bbox_centers_x.append(bbox_center_x)
            bbox_centers_y.append(bbox_center_y)
            bbox_areas.append(bbox_width * bbox_height)

        avg_center_x: float = float(np.mean(bbox_centers_x))
        avg_center_y: float = float(np.mean(bbox_centers_y))

        delta_x: float = (avg_center_x - frame_center_x) / frame_width
        delta_y: float = (avg_center_y - frame_center_y) / frame_height

        # update tolerance based on zoom level
        self.center_tolerance_x = max(
            0.05, self.center_tolerance_x * (1 - self.ptz_metrics["zoom_level"])
        )
        self.center_tolerance_y = max(
            0.05, self.center_tolerance_y * (1 - self.ptz_metrics["zoom_level"])
        )
        # determinge pan and tilt directions with threshold to avoid jitter
        pan_direction: float = self._calculate_pan_tilt(
            delta_x, self.center_tolerance_x, self.pan_velocity
        )
        tilt_direction: float = self._calculate_pan_tilt(
            delta_y, self.center_tolerance_y, self.tilt_velocity, invert=True
        )

        zoom_direction: float = self._calculate_zoom(
            frame_width, frame_height, bbox_areas, bbox_centers_x, bbox_centers_y
        )

        return pan_direction, tilt_direction, zoom_direction

    def _calculate_pan_tilt(
        self, delta: float, tolerance: float, velocity: float, invert: bool = False
    ) -> float:
        # with direction
        if abs(delta) > tolerance:
            direction: float = -velocity * delta if invert else velocity * delta
            return max(-1.0, min(1.0, direction))  # normalize to [-1, 1]
        return 0.0

    def _calculate_zoom(
        self,
        frame_width: int,
        frame_height: int,
        bbox_areas: List[float],
        bbox_centers_x: List[float],
        bbox_centers_y: List[float],
    ) -> float:
        frame_area: float = frame_width * frame_height

        # target area ratio for object size in the frame to prevent over-zoom or under-zoom
        min_target_area_ratio: float = 0.03
        max_target_area_ratio: float = 0.1

        total_bbox_area: float = float(np.sum(bbox_areas))
        current_area_ratio: float = total_bbox_area / frame_area

        # calculate the farthest object from the center
        frame_center_x: float = frame_width / 2
        frame_center_y: float = frame_height / 2
        max_distance_from_center: float = max(
            np.sqrt(
                ((bbox_center_x - frame_center_x) / frame_width) ** 2
                + ((bbox_center_y - frame_center_y) / frame_height) ** 2
            )
            for bbox_center_x, bbox_center_y in zip(bbox_centers_x, bbox_centers_y)
        )

        # thresholds for zooming in and out based on area ratio and distance from center
        zoom_in_threshold: float = min_target_area_ratio * (
            1 - self.ptz_metrics["zoom_level"]
        )
        zoom_out_threshold: float = max_target_area_ratio * (
            1 + self.ptz_metrics["zoom_level"]
        )

        zoom_direction: float = 0.0

        if (
            current_area_ratio < zoom_in_threshold
            and self.ptz_metrics["zoom_level"] < self.max_zoom
        ):
            zoom_direction = self.zoom_velocity * (1 - max_distance_from_center)
        elif (
            current_area_ratio > zoom_out_threshold
            and self.ptz_metrics["zoom_level"] > self.min_zoom
        ):
            zoom_direction = -self.zoom_velocity * (1 + max_distance_from_center)

        # ensure zoom level stays within limits
        new_zoom_level: float = self.ptz_metrics["zoom_level"] + zoom_direction
        self.ptz_metrics["zoom_level"] = max(
            self.min_zoom, min(self.max_zoom, new_zoom_level)
        )

        return zoom_direction

    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
        try:
            request = self.ptz_service.create_type("ContinuousMove")
            request.ProfileToken = self.profile_token

            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            if not status:
                raise ValueError(
                    "GetStatus() returned None. Check camera connectivity and credentials."
                )
            if not hasattr(status, "Position"):
                raise ValueError(
                    "Status object does not contain a 'Position' attribute."
                )

            request.Velocity = status.Position
            request.Velocity.PanTilt.x = pan
            request.Velocity.PanTilt.y = tilt
            request.Velocity.Zoom.x = zoom

            self.ptz_metrics["zoom_level"] += zoom

            self.ptz_service.ContinuousMove(request)
            self.is_moving = True
        except exceptions.ONVIFError as e:
            print(f"Error in continuous move: {e}")

    def stop_movement(self) -> None:
        if self.is_moving:
            try:
                request = self.ptz_service.create_type("Stop")
                request.ProfileToken = self.profile_token
                request.PanTilt = True
                request.Zoom = True
                self.ptz_service.Stop(request)
                self.is_moving = False
            except exceptions.ONVIFError as e:
                print(f"Error stopping PTZ movement: {e}")

    def move_to_default_position(self) -> None:
        # home_pan = -0.550611138
        # home_tilt = -0.531818211
        # home_zoom = 0.0499999933
        try:
            request = self.ptz_service.create_type("AbsoluteMove")
            request.ProfileToken = self.profile_token

            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            if not status:
                raise ValueError(
                    "GetStatus() returned None. Check camera connectivity and credentials."
                )
            if not hasattr(status, "Position"):
                raise ValueError(
                    "Status object does not contain a 'Position' attribute."
                )

            request.Position = status.Position
            request.Position.PanTilt.x = self.home_pan
            request.Position.PanTilt.y = self.home_tilt
            request.Position.Zoom.x = self.home_zoom

            # self.ptz_metrics["zoom_level"] = self.default_position['zoom']
            self.ptz_metrics["zoom_level"] = self.home_zoom

            self.ptz_service.AbsoluteMove(request)
        except exceptions.ONVIFError as e:
            print(f"Error moving to default position: {e}")

    def reset_camera_position(self) -> None:
        self.stop_movement()
        self.move_to_default_position()

    def track(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> None:
        if bboxes is None or len(bboxes) == 0:
            # no object detected
            current_time: float = time.time()
            if (
                current_time - self.last_detection_time > self.no_object_timeout
                and not self.is_at_default_position
            ):
                # self.stop_movement()  # stop any current movement
                # self.move_to_default_position()  # move to default position
                thread = threading.Thread(target=self.reset_camera_position, args=())
                thread.start()

                self.is_at_default_position = True

                print("No object detected. Moving to default zoom level.")
            else:
                print("No object detected. Waiting...")
            return

        # object(s) detected; update last detection time
        self.last_detection_time = time.time()

        # throtle movement commands to prevent jitter
        if time.time() - self.last_move_time < self.move_throttle_time:
            print("Throttling movement to prevent jitter.")
            return

        pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bboxes)

        # if no movement is needed, stop the camera
        if pan == 0 and tilt == 0 and zoom == 0:
            self.stop_movement()
        else:
            # enqueue movement to smooth out commands
            self._enqueue_move(pan, tilt, zoom)

        # upddate the last move time to current time
        self.last_move_time = time.time()
        self.is_at_default_position = False

    def _enqueue_move(self, pan: float, tilt: float, zoom: float) -> None:
        self.move_queue.put((pan, tilt, zoom))

    def _process_move_queue(self) -> None:
        while True:
            try:
                pan, tilt, zoom = self.move_queue.get(timeout=1)
                self.continuous_move(pan, tilt, zoom)
                time.sleep(0.1)
                self.move_queue.task_done()
            except queue.Empty:
                continue

    def _calibrate_camera(self) -> None:
        self.calibrating = True
        # TODO: move to preset monitoring position
        self.calibrating = False

    def _predict_movement_time(self, pan: float, tilt: float) -> None:
        # predict the time required for a movement based on pan and tilt
        combined_movement: float = abs(pan) + abs(tilt)
        # return np.dot(self.move_coefficients, [1, combined_movement])
        pass
