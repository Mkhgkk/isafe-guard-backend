from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)
import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from .base import ONVIFCameraBase


class PTZAutoTracker(ONVIFCameraBase):
    """Advanced PTZ auto-tracking camera controller with patrol functionality."""
    
    def __init__(self, cam_ip: str, ptz_port: int, ptz_username: str, ptz_password: str) -> None:
        super().__init__(cam_ip, ptz_port, ptz_username, ptz_password)
        
        # Tracking tolerances
        self.center_tolerance_x: float = 0.1
        self.center_tolerance_y: float = 0.1

        # Movement velocities
        self.pan_velocity: float = 0.8
        self.tilt_velocity: float = 0.8
        self.zoom_velocity: float = 0.02

        # Zoom limits
        self.min_zoom: float = 0.1
        self.max_zoom: float = 0.3

        # Movement throttling
        self.last_move_time: float = time.time()
        self.move_throttle_time: float = 0.5

        # Object detection timeout
        self.no_object_timeout: float = 5
        self.last_detection_time: float = time.time()
        
        # Default/home position
        self.home_pan: float = 0
        self.home_tilt: float = 0
        self.home_zoom: float = self.min_zoom
        
        # Movement state
        self.is_moving: bool = False
        self.is_at_default_position: bool = False
        
        # Movement queue for smooth operations
        self.move_queue: queue.Queue[Tuple[float, float, float]] = queue.Queue()
        self.move_thread: threading.Thread = threading.Thread(target=self._process_move_queue)
        self.move_thread.daemon = True
        self.move_thread.start()

        # PTZ metrics
        self.ptz_metrics: Dict[str, float] = {
            "zoom_level": self.min_zoom,
        }
        
        self.calibrating: bool = False

        # Initialize patrol functionality
        self.add_patrol_functionality()

    def update_default_position(self, pan: float, tilt: float, zoom: float) -> None:
        """Update the default/home position."""
        self.home_pan = pan
        self.home_tilt = tilt
        self.home_zoom = zoom

    def calculate_movement(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: List[Tuple[float, float, float, float]],
    ) -> Tuple[float, float, float]:
        """Calculate the necessary pan, tilt, and zoom changes to keep objects centered."""
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

        # Update tolerance based on zoom level
        self.center_tolerance_x = max(
            0.05, self.center_tolerance_x * (1 - self.ptz_metrics["zoom_level"])
        )
        self.center_tolerance_y = max(
            0.05, self.center_tolerance_y * (1 - self.ptz_metrics["zoom_level"])
        )
        
        # Determine pan and tilt directions with threshold to avoid jitter
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
        """Calculate pan/tilt direction with tolerance."""
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
        """Calculate zoom direction based on object size and position."""
        frame_area: float = frame_width * frame_height

        # Target area ratio for object size in the frame
        min_target_area_ratio: float = 0.03
        max_target_area_ratio: float = 0.1

        total_bbox_area: float = float(np.sum(bbox_areas))
        current_area_ratio: float = total_bbox_area / frame_area

        # Calculate the farthest object from the center
        frame_center_x: float = frame_width / 2
        frame_center_y: float = frame_height / 2
        max_distance_from_center: float = max(
            np.sqrt(
                ((bbox_center_x - frame_center_x) / frame_width) ** 2
                + ((bbox_center_y - frame_center_y) / frame_height) ** 2
            )
            for bbox_center_x, bbox_center_y in zip(bbox_centers_x, bbox_centers_y)
        )

        # Thresholds for zooming in and out
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

        # Ensure zoom level stays within limits
        new_zoom_level: float = self.ptz_metrics["zoom_level"] + zoom_direction
        self.ptz_metrics["zoom_level"] = max(
            self.min_zoom, min(self.max_zoom, new_zoom_level)
        )

        return zoom_direction

    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
        """Override base class method to update internal zoom metrics."""
        super().continuous_move(pan, tilt, zoom)
        self.ptz_metrics["zoom_level"] += zoom
        self.is_moving = True

    def stop_movement(self) -> None:
        """Override base class method to update movement state."""
        if self.is_moving:
            super().stop_movement()
            self.is_moving = False

    def move_to_default_position(self) -> None:
        """Move camera to the default/home position."""
        try:
            self.absolute_move(self.home_pan, self.home_tilt, self.home_zoom)
            self.ptz_metrics["zoom_level"] = self.home_zoom
            self.is_at_default_position = True
        except Exception as e:
            log_event(logger, "error", f"Error moving to default position: {e}", event_type="error")

    def reset_camera_position(self) -> None:
        """Reset camera to default position."""
        self.stop_movement()
        self.move_to_default_position()

    def track(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> None:
        """Main tracking function."""
        if bboxes is None or len(bboxes) == 0:
            # No object detected
            current_time: float = time.time()
            if (
                current_time - self.last_detection_time > self.no_object_timeout
                and not self.is_at_default_position
            ):
                thread = threading.Thread(target=self.reset_camera_position)
                thread.daemon = True
                thread.start()
                self.is_at_default_position = True
            return

        # Object(s) detected; update last detection time
        self.last_detection_time = time.time()

        # Throttle movement commands to prevent jitter
        if time.time() - self.last_move_time < self.move_throttle_time:
            log_event(logger, "info", "Throttling movement to prevent jitter.", event_type="info")
            return

        pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bboxes)

        # If no movement is needed, stop the camera
        if pan == 0 and tilt == 0 and zoom == 0:
            self.stop_movement()
        else:
            # Enqueue movement to smooth out commands
            self._enqueue_move(pan, tilt, zoom)

        # Update the last move time
        self.last_move_time = time.time()
        self.is_at_default_position = False

    def _enqueue_move(self, pan: float, tilt: float, zoom: float) -> None:
        """Add movement to queue."""
        self.move_queue.put((pan, tilt, zoom))

    def _process_move_queue(self) -> None:
        """Process movement queue in separate thread."""
        while True:
            try:
                pan, tilt, zoom = self.move_queue.get(timeout=1)
                self.continuous_move(pan, tilt, zoom)
                time.sleep(0.1)
                self.move_queue.task_done()
            except queue.Empty:
                continue

    def _calibrate_camera(self) -> None:
        """Calibrate camera (placeholder for future implementation)."""
        self.calibrating = True
        # TODO: move to preset monitoring position
        self.calibrating = False

    def _predict_movement_time(self, pan: float, tilt: float) -> None:
        """Predict movement time (placeholder for future implementation)."""
        combined_movement: float = abs(pan) + abs(tilt)
        pass

    # Patrol functionality
    def add_patrol_functionality(self, patrol_area=None):
        """Add patrol functionality to the PTZ camera."""
        if patrol_area is None:
            self.patrol_area = {
                'zMin': 0.199530029, 
                'zMax': 0.489974976, 
                'xMin': 0.215444446, 
                'xMax': 0.391888916, 
                'yMin': -0.58170867, 
                'yMax': -1
            }
        else:
            self.patrol_area = patrol_area
            
        # Add patrol-related attributes
        self.is_patrolling = False
        self.patrol_thread = None
        self.patrol_x_step = 0.02
        self.patrol_y_step = 0.05
        self.patrol_dwell_time = 2.0
        self.patrol_stop_event = threading.Event()
        self.patrol_direction = "horizontal"
        self.zoom_during_patrol = self.patrol_area['zMin']

    def start_patrol(self, direction="horizontal"):
        """Start the patrol function in a separate thread."""
        if not hasattr(self, 'patrol_area'):
            self.add_patrol_functionality()
        
        if direction not in ["horizontal", "vertical"]:
            log_event(logger, "warning", f"Invalid patrol direction: {direction}. Using 'horizontal'.", event_type="warning")
            direction = "horizontal"
        
        self.patrol_direction = direction
            
        if self.is_patrolling:
            self.stop_patrol()
            
        self.is_patrolling = True
        self.patrol_stop_event.clear()
        self.patrol_thread = threading.Thread(target=self._patrol_routine)
        self.patrol_thread.daemon = True
        self.patrol_thread.start()
        log_event(logger, "info", f"Patrol started in {direction} progression mode", event_type="info")
        
    def stop_patrol(self):
        """Stop the patrol function."""
        if not self.is_patrolling:
            return
            
        self.patrol_stop_event.set()
        if self.patrol_thread:
            self.patrol_thread.join(timeout=5.0)
        self.is_patrolling = False
        self.stop_movement()
        log_event(logger, "info", "Patrol stopped", event_type="info")

    def _patrol_routine(self):
        """Main patrol routine that implements a scanning pattern."""
        try:
            zoom_level = self.zoom_during_patrol
            
            if self.patrol_direction == "horizontal":
                self._horizontal_patrol(zoom_level)
            else:
                self._vertical_patrol(zoom_level)
                
        except Exception as e:
            log_event(logger, "error", f"Error in patrol routine: {e}", event_type="error")
            self.is_patrolling = False

    def _horizontal_patrol(self, zoom_level):
        """Horizontal progression patrol (snake pattern)."""
        # Initialize patrol at starting position
        self.absolute_move(
            self.patrol_area['xMin'],
            self.patrol_area['yMin'],
            zoom_level
        )
        time.sleep(2.0)
        
        left_to_right = True
        
        while not self.patrol_stop_event.is_set():
            current_x = self.patrol_area['xMin']
            current_y = self.patrol_area['yMin']
            
            while current_y >= self.patrol_area['yMax'] and not self.patrol_stop_event.is_set():
                if left_to_right:
                    while current_x <= self.patrol_area['xMax'] and not self.patrol_stop_event.is_set():
                        self.absolute_move(current_x, current_y, zoom_level)
                        time.sleep(self.patrol_dwell_time)
                        current_x += self.patrol_x_step
                else:
                    while current_x >= self.patrol_area['xMin'] and not self.patrol_stop_event.is_set():
                        self.absolute_move(current_x, current_y, zoom_level)
                        time.sleep(self.patrol_dwell_time)
                        current_x -= self.patrol_x_step
                
                current_y -= self.patrol_y_step
                left_to_right = not left_to_right
                current_x = self.patrol_area['xMin'] if left_to_right else self.patrol_area['xMax']
            
            log_event(logger, "info", "Horizontal patrol cycle complete, restarting from beginning", event_type="info")

    def _vertical_patrol(self, zoom_level):
        """Vertical progression patrol (column pattern)."""
        # Initialize patrol at starting position
        self.absolute_move(
            self.patrol_area['xMin'],
            self.patrol_area['yMin'],
            zoom_level
        )
        time.sleep(2.0)
        
        top_to_bottom = True
        
        while not self.patrol_stop_event.is_set():
            current_x = self.patrol_area['xMin']
            current_y = self.patrol_area['yMin']
            
            while current_x <= self.patrol_area['xMax'] and not self.patrol_stop_event.is_set():
                if top_to_bottom:
                    while current_y >= self.patrol_area['yMax'] and not self.patrol_stop_event.is_set():
                        self.absolute_move(current_x, current_y, zoom_level)
                        time.sleep(self.patrol_dwell_time)
                        current_y -= self.patrol_y_step
                else:
                    while current_y <= self.patrol_area['yMin'] and not self.patrol_stop_event.is_set():
                        self.absolute_move(current_x, current_y, zoom_level)
                        time.sleep(self.patrol_dwell_time)
                        current_y += self.patrol_y_step
                
                current_x += self.patrol_x_step
                top_to_bottom = not top_to_bottom
                current_y = self.patrol_area['yMin'] if top_to_bottom else self.patrol_area['yMax']
            
            log_event(logger, "info", "Vertical patrol cycle complete, restarting from beginning", event_type="info")

    def is_patrol_active(self):
        """Returns whether patrol is currently active."""
        return self.is_patrolling

    def get_patrol_direction(self):
        """Returns the current patrol direction."""
        if not hasattr(self, 'patrol_direction'):
            return "horizontal"
        return self.patrol_direction

    def set_patrol_parameters(self, x_step=None, y_step=None, dwell_time=None, 
                            zoom_level=None, direction=None):
        """Set patrol parameters."""
        if not hasattr(self, 'patrol_area'):
            self.add_patrol_functionality()
            
        if x_step is not None:
            self.patrol_x_step = x_step
        if y_step is not None:
            self.patrol_y_step = y_step
        if dwell_time is not None:
            self.patrol_dwell_time = dwell_time
        if zoom_level is not None:
            if self.patrol_area['zMin'] <= zoom_level <= self.patrol_area['zMax']:
                self.zoom_during_patrol = zoom_level
            else:
                log_event(logger, "warning", f"Zoom level {zoom_level} is outside allowed range", event_type="warning")
        if direction is not None:
            if direction in ["horizontal", "vertical"]:
                self.patrol_direction = direction
            else:
                log_event(logger, "warning", f"Invalid patrol direction: {direction}", event_type="warning")