import queue
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .base import ONVIFCameraBase
from .patrol_mixin import PatrolMixin
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


# Autotracking constants from reference implementation
AUTOTRACKING_MAX_AREA_RATIO = 0.5
AUTOTRACKING_MAX_MOVE_METRICS = 500
AUTOTRACKING_MOTION_MAX_POINTS = 500
AUTOTRACKING_MOTION_MIN_DISTANCE = 20
AUTOTRACKING_ZOOM_EDGE_THRESHOLD = 0.05
AUTOTRACKING_ZOOM_IN_HYSTERESIS = 0.95
AUTOTRACKING_ZOOM_OUT_HYSTERESIS = 1.05



class PTZAutoTracker(ONVIFCameraBase, PatrolMixin):
    """Advanced PTZ auto-tracking camera controller with patrol functionality."""
    
    # Default configuration constants
    DEFAULT_CENTER_TOLERANCE_X = 0.1
    DEFAULT_CENTER_TOLERANCE_Y = 0.1
    DEFAULT_PAN_VELOCITY = 0.8
    DEFAULT_TILT_VELOCITY = 0.8
    DEFAULT_ZOOM_VELOCITY = 0.02
    DEFAULT_MIN_ZOOM = 0.1
    DEFAULT_MAX_ZOOM = 0.3
    DEFAULT_MOVE_THROTTLE_TIME = 0.5
    DEFAULT_NO_OBJECT_TIMEOUT = 5.0
    
    # Target area ratios for zoom calculation
    MIN_TARGET_AREA_RATIO = 0.1
    MAX_TARGET_AREA_RATIO = 0.5
    
    def __init__(self, cam_ip: str, ptz_port: int, ptz_username: str, ptz_password: str, profile_name: Optional[str] = None) -> None:
        super().__init__(cam_ip, ptz_port, ptz_username, ptz_password, profile_name)
        
        # Initialize tracking configuration
        self._init_tracking_config()
        
        # Initialize movement state
        self._init_movement_state()
        
        # Initialize patrol functionality
        self.add_patrol_functionality()

    def _init_tracking_config(self) -> None:
        """Initialize tracking configuration parameters."""
        # Tracking tolerances
        self.center_tolerance_x: float = self.DEFAULT_CENTER_TOLERANCE_X
        self.center_tolerance_y: float = self.DEFAULT_CENTER_TOLERANCE_Y

        # Movement velocities
        self.pan_velocity: float = self.DEFAULT_PAN_VELOCITY
        self.tilt_velocity: float = self.DEFAULT_TILT_VELOCITY
        self.zoom_velocity: float = self.DEFAULT_ZOOM_VELOCITY

        # Zoom limits
        self.min_zoom: float = self.DEFAULT_MIN_ZOOM
        self.max_zoom: float = self.DEFAULT_MAX_ZOOM

        # Movement throttling
        self.move_throttle_time: float = self.DEFAULT_MOVE_THROTTLE_TIME

        # Object detection timeout
        self.no_object_timeout: float = self.DEFAULT_NO_OBJECT_TIMEOUT

        # Zoom factor for target box calculations
        self.zoom_factor: float = 1.0
        
    def _init_movement_state(self) -> None:
        """Initialize movement state variables."""
        # Timing
        self.last_move_time: float = time.time()
        self.last_detection_time: float = time.time()
        self.ptz_start_time: float = 0.0
        self.ptz_stop_time: float = 0.0

        # Default/home position
        self.home_pan: float = 0
        self.home_tilt: float = 0
        self.home_zoom: float = self.min_zoom

        # Movement state
        self.is_moving: bool = False
        self.is_at_default_position: bool = False
        self.motor_stopped: bool = True

        # PTZ metrics
        self.ptz_metrics: Dict[str, float] = {
            "zoom_level": self.min_zoom,
        }

        self.calibrating: bool = False

        # Tracked object state
        self.tracked_object: Optional[Dict[str, Any]] = None
        self.tracked_object_history: deque = deque(maxlen=30)  # ~2 seconds at 15 fps
        self.tracked_object_metrics: Dict[str, Any] = {
            "max_target_box": AUTOTRACKING_MAX_AREA_RATIO ** (1 / self.zoom_factor)
        }

        # Movement metrics for calibration
        self.move_metrics: List[Dict[str, float]] = []
        self.intercept: Optional[float] = None
        self.move_coefficients: List[float] = []
        self.zoom_time: float = 0.0

        # Initialize movement queue
        self._init_movement_queue()
        
    def _init_movement_queue(self) -> None:
        """Initialize movement queue and processing thread."""
        self.move_queue: queue.Queue[Tuple[float, float, float, float]] = queue.Queue()
        self.move_queue_lock: threading.Lock = threading.Lock()
        self.move_thread: threading.Thread = threading.Thread(target=self._process_move_queue)
        self.move_thread.daemon = True
        self.move_thread.start()

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

        # Extract bbox data
        bbox_data = self._extract_bbox_data(bboxes)
        
        # Calculate frame deltas
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2
        delta_x = (bbox_data['avg_center_x'] - frame_center_x) / frame_width
        delta_y = (bbox_data['avg_center_y'] - frame_center_y) / frame_height

        # Update tolerances based on zoom level
        self._update_tolerances_for_zoom()
        
        # Calculate movements
        pan_direction = self._calculate_pan_tilt(
            delta_x, self.center_tolerance_x, self.pan_velocity
        )
        tilt_direction = self._calculate_pan_tilt(
            delta_y, self.center_tolerance_y, self.tilt_velocity, invert=True
        )
        zoom_direction = self._calculate_zoom(
            frame_width, frame_height, bbox_data['areas'], 
            bbox_data['centers_x'], bbox_data['centers_y']
        )

        return pan_direction, tilt_direction, zoom_direction
    
    def _extract_bbox_data(self, bboxes: List[Tuple[float, float, float, float]]) -> Dict[str, Any]:
        """Extract and process bounding box data."""
        centers_x: List[float] = []
        centers_y: List[float] = []
        areas: List[float] = []

        for bbox in bboxes:
            x1, y1, x2, y2 = bbox
            bbox_width = x2 - x1
            bbox_height = y2 - y1
            center_x = x1 + bbox_width / 2
            center_y = y1 + bbox_height / 2

            centers_x.append(center_x)
            centers_y.append(center_y)
            areas.append(bbox_width * bbox_height)

        return {
            'centers_x': centers_x,
            'centers_y': centers_y,
            'areas': areas,
            'avg_center_x': float(np.mean(centers_x)),
            'avg_center_y': float(np.mean(centers_y))
        }
    
    def _update_tolerances_for_zoom(self) -> None:
        """Update center tolerances based on current zoom level."""
        zoom_factor = 1 - self.ptz_metrics["zoom_level"]
        self.center_tolerance_x = max(0.05, self.DEFAULT_CENTER_TOLERANCE_X * zoom_factor)
        self.center_tolerance_y = max(0.05, self.DEFAULT_CENTER_TOLERANCE_Y * zoom_factor)

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

        # Use class constants for target area ratios
        min_target_area_ratio = self.MIN_TARGET_AREA_RATIO
        max_target_area_ratio = self.MAX_TARGET_AREA_RATIO

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
        """Main tracking function with patrol-aware behavior."""
        # Handle tracking differently when patrolling
        if self.is_patrolling:
            self._track_during_patrol(frame_width, frame_height, bboxes)
        else:
            self._track_normal_mode(frame_width, frame_height, bboxes)

    def _track_normal_mode(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> None:
        """Original tracking behavior for non-patrol mode."""
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

    def _track_during_patrol(
        self,
        frame_width: int,
        frame_height: int,
        bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> None:
        """Tracking behavior during patrol mode - simplified transition logic."""
        # Check if patrol is resting at home - no tracking during rest period
        if getattr(self, "is_resting_at_home", False):
            log_event(
                logger,
                "debug",
                "Patrol is resting at home - tracking paused",
                event_type="patrol_rest_tracking_blocked",
            )
            return

        # Check if focus is enabled during patrol
        if not self.can_focus_during_patrol():
            log_event(
                logger,
                "debug",
                "Focus disabled during patrol - skipping tracking",
                event_type="patrol_focus_disabled",
            )
            return

        current_time = time.time()

        # Handle cooldown period
        if self._handle_cooldown_period(current_time, bboxes):
            return

        # Handle object detection and tracking
        if bboxes is not None and len(bboxes) > 0:
            self._handle_object_detection_during_patrol(current_time, frame_width, frame_height, bboxes)
        else:
            self._handle_no_objects_during_patrol(current_time)
    
    def _handle_cooldown_period(self, current_time: float, bboxes: Optional[List[Tuple[float, float, float, float]]]) -> bool:
        """Handle tracking cooldown period. Returns True if in cooldown."""
        if not self.is_in_tracking_cooldown:
            return False
            
        if current_time >= self.tracking_cooldown_end_time:
            self.is_in_tracking_cooldown = False
            self.tracking_cooldown_end_time = 0.0
            log_event(logger, "info", "Tracking cooldown period ended - objects can be tracked again", event_type="tracking_cooldown_end")
            return False
        
        # Still in cooldown
        if bboxes is not None and len(bboxes) > 0:
            remaining_time = self.tracking_cooldown_end_time - current_time
            log_event(logger, "debug", f"Objects detected but in cooldown period ({remaining_time:.1f}s remaining)", event_type="tracking_cooldown_active")
        return True
    
    def _handle_object_detection_during_patrol(self, current_time: float, frame_width: int, frame_height: int, bboxes: List[Tuple[float, float, float, float]]) -> None:
        """Handle object detection during patrol."""
        if not self.is_focusing_on_object:
            log_event(logger, "info", "Object detected during patrol - starting object focus", event_type="object_focus_start")
            self._start_object_focus()
            self.object_focus_start_time = current_time
            
        # Continue focusing if within duration
        if current_time - self.object_focus_start_time < self.object_focus_duration:
            self._track_object_with_enhanced_zoom(frame_width, frame_height, bboxes, current_time)
        else:
            log_event(logger, "info", "Object focus duration exceeded - ending tracking", event_type="object_focus_timeout")
            self._end_object_focus_with_cooldown()
    
    def _handle_no_objects_during_patrol(self, current_time: float) -> None:
        """Handle case when no objects are detected during patrol."""
        if self.is_focusing_on_object:
            focus_elapsed = current_time - self.object_focus_start_time
            min_focus_duration = getattr(self, "min_object_focus_duration", 5.0)

            # Only end focus if minimum focus duration has been met
            if focus_elapsed >= min_focus_duration:
                log_event(logger, "info", f"Object lost during focus after {focus_elapsed:.1f}s (min {min_focus_duration}s met) - ending tracking", event_type="object_lost")
                self._end_object_focus_with_cooldown()
            elif focus_elapsed >= 1.0:
                # Object lost but minimum focus time not met - keep focusing position
                log_event(logger, "debug", f"Object lost but minimum focus time not met ({focus_elapsed:.1f}s / {min_focus_duration}s) - holding position", event_type="object_lost_holding")
    
    def _track_object_with_enhanced_zoom(self, frame_width: int, frame_height: int, bboxes: List[Tuple[float, float, float, float]], current_time: float) -> None:
        """Track object with enhanced zoom capabilities."""
        original_max_zoom = self.max_zoom
        self.max_zoom = self.focus_max_zoom
        
        try:
            pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bboxes)
            if not (pan == 0 and tilt == 0 and zoom == 0):
                self._enqueue_move(pan, tilt, zoom)
            self.last_move_time = current_time
            self.last_detection_time = current_time
        finally:
            self.max_zoom = original_max_zoom

    def _start_object_focus(self) -> None:
        """Start focusing on detected object during patrol - simplified."""
        try:
            self._store_current_patrol_position()
            self._set_focus_state()
            log_event(logger, "debug", "Object focus started - patrol paused", event_type="patrol_pause")
        except Exception as e:
            log_event(logger, "error", f"Error starting object focus: {e}", event_type="error")
            self._reset_focus_state()
    
    def _set_focus_state(self) -> None:
        """Set the focus state for object tracking."""
        self.is_focusing_on_object = True
        self.patrol_paused = True
        self.patrol_pause_event.set()
    
    def _reset_focus_state(self) -> None:
        """Reset focus state on error."""
        self.is_focusing_on_object = False
        self.patrol_paused = False

    def _store_current_patrol_position(self) -> None:
        """Store the current patrol position to return to after tracking."""
        try:
            current_x, current_y = self._calculate_current_patrol_coordinates()
            self.patrol_position_before_tracking = self._create_patrol_position_dict(current_x, current_y)
            log_event(logger, "debug", f"Stored patrol position: step({self.current_patrol_x_step},{self.current_patrol_y_step}) coord({current_x:.3f},{current_y:.3f})", event_type="patrol_position_stored")
        except Exception as e:
            log_event(logger, "error", f"Error storing patrol position: {e}", event_type="error")
            self.patrol_position_before_tracking = None
    
    def _calculate_current_patrol_coordinates(self) -> Tuple[float, float]:
        """Calculate current patrol coordinates based on grid position."""
        current_x = self.patrol_area['xMin'] + (self.current_patrol_x_step * self.patrol_x_step)
        current_y = self.patrol_area['yMin'] - (self.current_patrol_y_step * self.patrol_y_step)
        
        # Clamp coordinates to patrol area
        current_x = max(self.patrol_area['xMin'], min(self.patrol_area['xMax'], current_x))
        current_y = max(self.patrol_area['yMax'], min(self.patrol_area['yMin'], current_y))
        
        return current_x, current_y
    
    def _create_patrol_position_dict(self, current_x: float, current_y: float) -> Dict[str, Any]:
        """Create patrol position dictionary for storage."""
        return {
            'x_step': self.current_patrol_x_step,
            'y_step': self.current_patrol_y_step,
            'left_to_right': self.current_patrol_left_to_right,
            'top_to_bottom': self.current_patrol_top_to_bottom,
            'x_coord': current_x,
            'y_coord': current_y,
            'zoom': self.zoom_during_patrol
        }

    def _return_to_stored_patrol_position(self):
        """Return camera to the stored patrol position before tracking - runs on separate thread."""
        if self.patrol_position_before_tracking is None:
            log_event(logger, "warning", "No stored patrol position to return to", event_type="warning")
            return
        
        def _position_return_thread():
            """Separate thread for position return to avoid blocking."""
            try:
                self.position_return_in_progress = True
                stored = self.patrol_position_before_tracking
                
                if stored is None:
                    log_event(logger, "warning", "Stored position is None in return thread", event_type="warning")
                    self.position_return_in_progress = False
                    return
                
                log_event(logger, "info", f"Returning to patrol position: step({stored['x_step']},{stored['y_step']}) coord({stored['x_coord']:.3f},{stored['y_coord']:.3f})", event_type="patrol_position_return")
                
                # Move camera back to exact position
                self.absolute_move(stored['x_coord'], stored['y_coord'], stored['zoom'])
                
                # Restore patrol state
                self.current_patrol_x_step = stored['x_step']
                self.current_patrol_y_step = stored['y_step']
                self.current_patrol_left_to_right = stored['left_to_right']
                self.current_patrol_top_to_bottom = stored['top_to_bottom']
                
                # Allow time for movement to complete
                time.sleep(1.0)
                
                self.position_return_in_progress = False
                log_event(logger, "debug", "Position return completed", event_type="patrol_position_return_complete")
                
            except Exception as e:
                self.position_return_in_progress = False
                log_event(logger, "error", f"Error returning to stored patrol position: {e}", event_type="error")
        
        # Start position return in separate thread
        position_thread = threading.Thread(target=_position_return_thread)
        position_thread.daemon = True
        position_thread.start()
        
        # Don't wait for completion - let it run asynchronously

    def _clear_movement_queue(self) -> None:
        """Clear all pending movements from the movement queue."""
        try:
            cleared_count = 0
            while not self.move_queue.empty():
                try:
                    self.move_queue.get_nowait()
                    self.move_queue.task_done()
                    cleared_count += 1
                except queue.Empty:
                    break
            if cleared_count > 0:
                log_event(logger, "debug", f"Movement queue cleared ({cleared_count} items)", event_type="movement_queue_cleared")
        except Exception as e:
            log_event(logger, "warning", f"Error clearing movement queue: {e}", event_type="warning")

    def _end_object_focus_with_cooldown(self):
        """End object focus, return to patrol position, and start cooldown period."""
        try:
            log_event(logger, "info", "Ending object focus and resuming patrol", event_type="object_focus_end")
            
            # Clear movement queue and stop current movements first
            self.stop_movement()
            self._clear_movement_queue()
            
            # Start cooldown period immediately (don't wait for position return)
            self.tracking_cooldown_end_time = time.time() + self.patrol_tracking_cooldown_duration
            self.is_in_tracking_cooldown = True
            
            # Reset tracking state immediately
            self.is_focusing_on_object = False
            self.object_focus_start_time = 0.0
            
            # Resume patrol immediately (position return happens async)
            self.patrol_paused = False
            self.patrol_pause_event.clear()
            self.patrol_resume_event.set()
            
            # Start position return on separate thread (non-blocking)
            self._return_to_stored_patrol_position()
            
            # Clean up stored position after starting the return thread
            # Note: Don't clear immediately as the thread needs access to it
            threading.Timer(2.0, self._cleanup_stored_position).start()
            
            log_event(logger, "info", f"Patrol resumed with {self.patrol_tracking_cooldown_duration}s cooldown - position return in progress", event_type="patrol_resume")
            
        except Exception as e:
            log_event(logger, "error", f"Error ending object focus: {e}", event_type="error")
            # Force reset state on error
            self._force_reset_tracking_state()

    def _cleanup_stored_position(self):
        """Clean up stored position after position return completes."""
        self.patrol_position_before_tracking = None
        log_event(logger, "debug", "Stored patrol position cleaned up", event_type="patrol_position_cleanup")

    def _force_reset_tracking_state(self) -> None:
        """Force reset all tracking-related state in case of errors."""
        log_event(logger, "warning", "Force resetting tracking state", event_type="tracking_state_reset")
        
        # Reset all tracking flags
        self._reset_tracking_flags()
        
        # Reset patrol state
        self._reset_patrol_state()
        
        # Clear position data
        self.patrol_position_before_tracking = None
        
        # Stop movements safely
        self._safe_stop_movements()
    
    def _reset_tracking_flags(self) -> None:
        """Reset all tracking-related flags."""
        self.is_focusing_on_object = False
        self.object_focus_start_time = 0.0
        self.is_in_tracking_cooldown = False
        self.tracking_cooldown_end_time = 0.0
        
    def _reset_patrol_state(self) -> None:
        """Reset patrol state flags and events."""
        self.patrol_paused = False
        self.patrol_pause_event.clear()
        self.patrol_resume_event.set()
        
    def _safe_stop_movements(self) -> None:
        """Safely stop movements and clear queue."""
        try:
            self.stop_movement()
            self._clear_movement_queue()
        except Exception as e:
            log_event(logger, "warning", f"Error stopping movements during reset: {e}", event_type="warning")

    def _advance_patrol_step(self):
        """Called when patrol advances to next position - kept for compatibility."""
        pass

    def _enqueue_move(self, pan: float, tilt: float, zoom: float, frame_time: Optional[float] = None) -> None:
        """
        Add movement to queue with proper locking and value splitting.

        Args:
            pan: Pan value (-1 to 1)
            tilt: Tilt value (-1 to 1)
            zoom: Zoom value (-1 to 1)
            frame_time: Optional frame time for PTZ movement tracking
        """
        def split_value(value: float, suppress_diff: bool = True) -> Tuple[float, float]:
            """Split large values into clipped and remainder."""
            clipped = np.clip(value, -1, 1)

            # Don't make small movements
            if -0.05 < clipped < 0.05 and suppress_diff:
                diff = 0.0
            else:
                diff = value - clipped

            return clipped, diff

        # Check if PTZ is currently moving or queue is locked
        if frame_time is not None and self.ptz_moving_at_frame_time(frame_time):
            logger.debug(
                f"PTZ moving at frame time {frame_time}, skipping move: pan={pan}, tilt={tilt}, zoom={zoom}"
            )
            return

        if self.move_queue_lock.locked():
            logger.debug("Move queue locked, skipping enqueue")
            return

        # Split up large moves if necessary
        while pan != 0 or tilt != 0 or zoom != 0:
            pan, pan_diff = split_value(pan)
            tilt, tilt_diff = split_value(tilt)
            zoom, zoom_diff = split_value(zoom, False)

            if pan != 0 or tilt != 0 or zoom != 0:
                logger.debug(f"Enqueue movement: pan={pan}, tilt={tilt}, zoom={zoom}")
                move_data = (pan, tilt, zoom, frame_time or time.time())
                self.move_queue.put(move_data)

            # Continue with remainder
            pan = pan_diff
            tilt = tilt_diff
            zoom = zoom_diff

    def _process_move_queue(self) -> None:
        """Process movement queue in separate thread with proper locking."""
        while True:
            try:
                pan, tilt, zoom, frame_time = self.move_queue.get(timeout=1)

                with self.move_queue_lock:
                    # Double check PTZ isn't moving
                    if self.ptz_moving_at_frame_time(frame_time):
                        logger.debug(
                            f"PTZ moving during dequeue (frame_time: {frame_time}), skipping move"
                        )
                        self.move_queue.task_done()
                        continue

                    # Record movement start time
                    movement_start = time.time()
                    self.ptz_start_time = movement_start
                    self.motor_stopped = False

                    # Execute movement
                    self.continuous_move(pan, tilt, zoom)

                    # Wait briefly for movement to complete
                    time.sleep(0.1)

                    # Record movement end time
                    movement_end = time.time()
                    self.ptz_stop_time = movement_end
                    self.motor_stopped = True

                    # Save metrics for calibration if intercept exists and we have room
                    if (
                        self.intercept is not None
                        and len(self.move_metrics) < AUTOTRACKING_MAX_MOVE_METRICS
                        and (pan != 0 or tilt != 0)
                    ):
                        logger.debug("Adding new values to move metrics")
                        self.move_metrics.append({
                            "pan": pan,
                            "tilt": tilt,
                            "start_timestamp": movement_start,
                            "end_timestamp": movement_end,
                        })

                        # Calculate new coefficients if we have enough data
                        self._calculate_move_coefficients()

                    # Log predicted vs actual if we have coefficients
                    if self.move_coefficients:
                        predicted_time = self._predict_movement_time(pan, tilt)
                        actual_time = movement_end - movement_start
                        logger.debug(
                            f"Movement time - predicted: {predicted_time:.3f}s, actual: {actual_time:.3f}s"
                        )

                self.move_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                log_event(logger, "error", f"Error processing move queue: {e}", event_type="error")
                self.move_queue.task_done()

    def _should_zoom_in(
        self,
        frame_width: int,
        frame_height: int,
        box: Tuple[float, float, float, float],
        predicted_time: float = 0,
        debug_zooming: bool = False,
    ) -> Optional[bool]:
        """
        Determine if camera should zoom in or out.

        Returns:
            True if should zoom in, False if should zoom out, None to do nothing
        """
        bb_left, bb_top, bb_right, bb_bottom = box

        # Calculate velocity threshold
        if self.move_coefficients:
            predicted_movement_time = self._predict_movement_time(1, 1)
            camera_fps = 15.0  # Default FPS
            velocity_threshold_x = frame_width / predicted_movement_time / camera_fps
            velocity_threshold_y = frame_height / predicted_movement_time / camera_fps
        else:
            velocity_threshold_x = frame_width * 0.02
            velocity_threshold_y = frame_height * 0.02

        # Check frame edges
        touching_frame_edges = self._touching_frame_edges(frame_width, frame_height, box)

        # Check if object is centered
        below_distance_threshold = self.tracked_object_metrics.get("below_distance_threshold", False)

        # Check dimension threshold
        below_dimension_threshold = (bb_right - bb_left) <= frame_width * (
            self.zoom_factor + 0.1
        ) and (bb_bottom - bb_top) <= frame_height * (self.zoom_factor + 0.1)

        # Check velocity
        average_velocity = self.tracked_object_metrics.get("velocity", np.zeros((4,)))
        below_velocity_threshold = np.all(
            np.abs(average_velocity) < np.tile([velocity_threshold_x, velocity_threshold_y], 2)
        ) or np.all(average_velocity == 0)

        # Calculate target area
        if not predicted_time:
            calculated_target_box = self.tracked_object_metrics.get("target_box", 0)
        else:
            if "area_coefficients" in self.tracked_object_metrics:
                area_prediction = self._predict_area_after_time(predicted_time)
                calculated_target_box = (
                    self.tracked_object_metrics.get("target_box", 0)
                    + area_prediction / (frame_width * frame_height)
                )
            else:
                calculated_target_box = self.tracked_object_metrics.get("target_box", 0)

        max_target_box = self.tracked_object_metrics.get("max_target_box", AUTOTRACKING_MAX_AREA_RATIO)
        below_area_threshold = calculated_target_box < max_target_box

        # Hysteresis
        zoom_out_hysteresis = calculated_target_box > max_target_box * AUTOTRACKING_ZOOM_OUT_HYSTERESIS
        zoom_in_hysteresis = calculated_target_box < max_target_box * AUTOTRACKING_ZOOM_IN_HYSTERESIS

        # Zoom limits
        at_max_zoom = self.ptz_metrics["zoom_level"] >= self.max_zoom
        at_min_zoom = self.ptz_metrics["zoom_level"] <= self.min_zoom

        if debug_zooming:
            logger.debug(f"Zoom test: touching edges: {touching_frame_edges}")
            logger.debug(f"Zoom test: below distance threshold: {below_distance_threshold}")
            logger.debug(
                f"Zoom test: below area threshold: {below_area_threshold} (target: {calculated_target_box:.4f}, max: {max_target_box:.4f})"
            )
            logger.debug(f"Zoom test: below dimension threshold: {below_dimension_threshold}")
            logger.debug(f"Zoom test: below velocity threshold: {below_velocity_threshold}")
            logger.debug(f"Zoom test: at max zoom: {at_max_zoom}, at min zoom: {at_min_zoom}")
            logger.debug(f"Zoom test: zoom in hysteresis: {zoom_in_hysteresis}")
            logger.debug(f"Zoom test: zoom out hysteresis: {zoom_out_hysteresis}")

        # Zoom in conditions
        if (
            zoom_in_hysteresis
            and touching_frame_edges == 0
            and below_velocity_threshold
            and below_dimension_threshold
            and below_area_threshold
            and not at_max_zoom
        ):
            return True

        # Zoom out conditions
        if (
            (
                zoom_out_hysteresis
                and not at_max_zoom
                and (not below_area_threshold or not below_dimension_threshold)
            )
            or (zoom_out_hysteresis and not below_area_threshold and at_max_zoom)
            or (
                touching_frame_edges == 1
                and (below_distance_threshold or not below_dimension_threshold)
            )
            or touching_frame_edges > 1
            or not below_velocity_threshold
        ) and not at_min_zoom:
            return False

        return None

    def _predict_area_after_time(self, time_delta: float) -> float:
        """Predict object area after given time using area coefficients."""
        if (
            "area_coefficients" not in self.tracked_object_metrics
            or self.tracked_object_metrics["area_coefficients"] is None
        ):
            return 0.0

        if not self.tracked_object_history:
            return 0.0

        last_frame_time = self.tracked_object_history[-1].get("frame_time", 0)
        predicted_time = last_frame_time + time_delta

        return float(np.dot(self.tracked_object_metrics["area_coefficients"], [predicted_time]))

    def _get_zoom_amount(
        self,
        frame_width: int,
        frame_height: int,
        obj_box: Tuple[float, float, float, float],
        predicted_box: Tuple[float, float, float, float],
        predicted_movement_time: float,
        debug_zoom: bool = True,
    ) -> float:
        """
        Calculate zoom amount based on object size and position.

        Returns:
            Zoom value (negative for zoom out, positive for zoom in)
        """
        zoom = 0.0

        # Don't zoom on initial move
        if "target_box" not in self.tracked_object_metrics:
            target_box = max(
                obj_box[2] - obj_box[0], obj_box[3] - obj_box[1]
            ) ** 2 / (frame_width * frame_height)

            zoom = target_box ** self.zoom_factor
            if zoom > self.tracked_object_metrics["max_target_box"]:
                zoom = -(1 - zoom)

            logger.debug(
                f"Initial zoom calculation - target: {target_box:.4f}, max: {self.tracked_object_metrics['max_target_box']:.4f}, zoom: {zoom:.4f}"
            )
            return zoom

        # Determine zoom direction
        result = self._should_zoom_in(
            frame_width, frame_height, predicted_box, predicted_movement_time, debug_zoom
        )

        if result is None:
            return 0.0

        # Calculate zoom amount
        if predicted_movement_time:
            calculated_target_box = self.tracked_object_metrics[
                "target_box"
            ] + self._predict_area_after_time(predicted_movement_time) / (frame_width * frame_height)
            logger.debug(
                f"Zooming prediction: predicted time: {predicted_movement_time:.3f}s, "
                f"original: {self.tracked_object_metrics['target_box']:.4f}, "
                f"calculated: {calculated_target_box:.4f}"
            )
        else:
            calculated_target_box = self.tracked_object_metrics["target_box"]

        # Calculate zoom value
        ratio = self.tracked_object_metrics["max_target_box"] / calculated_target_box
        zoom = (ratio - 1) / (ratio + 1)

        if not result:
            # Zoom out
            zoom = -(1 - zoom) if zoom > 0 else -(zoom * 2 + 1)
        else:
            # Zoom in
            zoom = 1 - zoom if zoom > 0 else (zoom * 2 + 1)

        logger.debug(
            f"Zooming: {result} (in/out), ratio: {ratio:.4f}, zoom amount: {zoom:.4f}"
        )

        return zoom

    def _calibrate_camera(self) -> None:
        """Calibrate camera (placeholder for future implementation)."""
        self.calibrating = True
        # TODO: Implement full calibration routine similar to reference
        # - Move camera through calibration positions
        # - Measure movement times
        # - Calculate zoom ranges
        # - Compute regression coefficients
        self.calibrating = False

    def _predict_movement_time(self, pan: float, tilt: float) -> float:
        """Predict movement time based on calibration data."""
        if self.intercept is None or not self.move_coefficients:
            # Fallback to simple estimate
            return abs(pan) + abs(tilt)

        combined_movement = abs(pan) + abs(tilt)
        input_data = np.array([self.intercept, combined_movement])
        return float(np.dot(self.move_coefficients, input_data))

    def ptz_moving_at_frame_time(self, frame_time: float) -> bool:
        """Determine if PTZ was in motion at the given frame time."""
        return (self.ptz_start_time != 0.0 and frame_time > self.ptz_start_time) and (
            self.ptz_stop_time == 0.0 or (self.ptz_start_time <= frame_time <= self.ptz_stop_time)
        )

    def _touching_frame_edges(
        self, frame_width: int, frame_height: int, box: Tuple[float, float, float, float]
    ) -> int:
        """Return count of frame edges the bounding box is touching."""
        bb_left, bb_top, bb_right, bb_bottom = box
        edge_threshold = AUTOTRACKING_ZOOM_EDGE_THRESHOLD

        return int(
            (bb_left < edge_threshold * frame_width)
            + (bb_right > (1 - edge_threshold) * frame_width)
            + (bb_top < edge_threshold * frame_height)
            + (bb_bottom > (1 - edge_threshold) * frame_height)
        )

    def _get_valid_velocity(
        self, velocities: np.ndarray, frame_width: int, frame_height: int, camera_fps: float = 15.0
    ) -> Tuple[bool, np.ndarray]:
        """
        Validate velocity estimates and return validity status with velocities.

        Returns:
            Tuple of (is_valid, velocities) where velocities is zero array if invalid
        """
        logger.debug(f"Velocity check: {tuple(np.round(velocities).flatten().astype(int))}")

        # If we are close enough to zero, return right away
        if np.all(np.round(velocities) == 0):
            return True, np.zeros((4,))

        # Thresholds
        x_mags_thresh = frame_width / camera_fps / 2
        y_mags_thresh = frame_height / camera_fps / 2
        dir_thresh = 0.93
        delta_thresh = 20
        var_thresh = 10

        # Check magnitude
        x_mags = np.abs(velocities[:, 0])
        y_mags = np.abs(velocities[:, 1])
        invalid_x_mags = np.any(x_mags > x_mags_thresh)
        invalid_y_mags = np.any(y_mags > y_mags_thresh)

        # Check delta
        delta = np.abs(velocities[0] - velocities[1])
        invalid_delta = np.any(delta > delta_thresh)

        # Check variance
        stdev_list = np.std(velocities, axis=0)
        high_variances = np.any(stdev_list > var_thresh)

        # Check direction difference
        velocities = np.round(velocities)
        invalid_dirs = False
        if not np.any(np.linalg.norm(velocities, axis=1)):
            cosine_sim = np.dot(velocities[0], velocities[1]) / (
                np.linalg.norm(velocities[0]) * np.linalg.norm(velocities[1])
            )
            dir_thresh = 0.6 if np.all(delta < delta_thresh / 2) else dir_thresh
            invalid_dirs = cosine_sim < dir_thresh

        # Combine
        invalid = (
            invalid_x_mags
            or invalid_y_mags
            or invalid_dirs
            or invalid_delta
            or high_variances
        )

        if invalid:
            logger.debug(
                f"Invalid velocity: {tuple(np.round(velocities, 2).flatten().astype(int))}: Invalid because: "
                + ", ".join(
                    [
                        var_name
                        for var_name, is_invalid in [
                            ("invalid_x_mags", invalid_x_mags),
                            ("invalid_y_mags", invalid_y_mags),
                            ("invalid_dirs", invalid_dirs),
                            ("invalid_delta", invalid_delta),
                            ("high_variances", high_variances),
                        ]
                        if is_invalid
                    ]
                )
            )
            return False, np.zeros((4,))
        else:
            logger.debug("Valid velocity")
            return True, velocities.flatten()

    def _get_distance_threshold(
        self, frame_width: int, frame_height: int, obj_box: Tuple[float, float, float, float], has_valid_velocity: bool
    ) -> float:
        """
        Calculate distance threshold for determining if object is centered enough.

        Returns threshold as percentage of frame dimension, scaled by object size.
        """
        obj_width = obj_box[2] - obj_box[0]
        obj_height = obj_box[3] - obj_box[1]

        max_obj = max(obj_width, obj_height)
        max_frame = frame_width if max_obj == obj_width else frame_height

        # Larger objects should lower the threshold, smaller objects should raise it
        scaling_factor = 1 - np.log(max_obj / max_frame)

        percentage = (
            0.08 if self.move_coefficients and has_valid_velocity else 0.03
        )
        distance_threshold = percentage * max_frame * scaling_factor

        logger.debug(f"Distance threshold: {distance_threshold}")
        return distance_threshold

    def _calculate_move_coefficients(self, calibration: bool = False) -> bool:
        """Calculate and update movement prediction coefficients from metrics."""
        # Calculate new coefficients when we have 50 more new values or during calibration
        if not calibration and (
            len(self.move_metrics) % 50 != 0
            or len(self.move_metrics) == 0
            or len(self.move_metrics) > AUTOTRACKING_MAX_MOVE_METRICS
        ):
            return False

        X = np.array([abs(d["pan"]) + abs(d["tilt"]) for d in self.move_metrics])
        y = np.array([d["end_timestamp"] - d["start_timestamp"] for d in self.move_metrics])

        # Simple linear regression with intercept
        X_with_intercept = np.column_stack((np.ones(X.shape[0]), X))
        coefficients = np.linalg.lstsq(X_with_intercept, y, rcond=None)[0]

        intercept, slope = coefficients

        # Define reasonable bounds for PTZ movement times
        MIN_MOVEMENT_TIME = 0.1  # Minimum time for any movement (100ms)
        MAX_MOVEMENT_TIME = 10.0  # Maximum time for any movement
        MAX_SLOPE = 2.0  # Maximum seconds per unit of movement

        coefficients_valid = (
            MIN_MOVEMENT_TIME <= intercept <= MAX_MOVEMENT_TIME and 0 < slope <= MAX_SLOPE
        )

        if not coefficients_valid:
            logger.warning("Autotracking calibration failed - coefficients out of bounds")
            return False

        # If coefficients are valid, proceed with updates
        self.move_coefficients = coefficients.tolist()

        # Only assign a new intercept if we're calibrating
        if calibration:
            self.intercept = y[0]

        logger.debug(
            f"New regression parameters - intercept: {self.intercept}, coefficients: {self.move_coefficients}"
        )

        return True

    def _remove_outliers(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove statistical outliers from area data using IQR method."""
        if len(data) <= 3:
            return data

        areas = [item["area"] for item in data]

        Q1 = np.percentile(areas, 25)
        Q3 = np.percentile(areas, 75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR

        filtered_data = [item for item in data if lower_bound <= item["area"] <= upper_bound]

        # Log removed values
        removed_values = [item for item in data if item not in filtered_data]
        if removed_values:
            logger.debug(f"Removed area outliers: {removed_values}")

        return filtered_data

    def is_autotracking(self) -> bool:
        """Check if currently tracking an object."""
        return self.tracked_object is not None

    def end_tracked_object(self, obj_id: str) -> None:
        """
        End tracking for a specific object.

        Args:
            obj_id: ID of the object to stop tracking
        """
        if self.tracked_object and self.tracked_object.get("id") == obj_id:
            logger.debug(f"End object tracking: {obj_id}")
            self.tracked_object = None
            self.tracked_object_metrics = {
                "max_target_box": AUTOTRACKING_MAX_AREA_RATIO ** (1 / self.zoom_factor)
            }

    def start_tracking_object(
        self,
        obj_id: str,
        obj_label: str,
        box: Tuple[float, float, float, float],
        frame_time: float,
        frame_width: int,
        frame_height: int,
    ) -> None:
        """
        Start tracking a new object.

        Args:
            obj_id: Unique identifier for the object
            obj_label: Label/class of the object
            box: Bounding box (x1, y1, x2, y2)
            frame_time: Timestamp of the frame
            frame_width: Width of the frame
            frame_height: Height of the frame
        """
        if self.tracked_object is not None:
            logger.warning(f"Already tracking object {self.tracked_object.get('id')}, ignoring new object {obj_id}")
            return

        logger.info(f"Starting to track new object: {obj_id} ({obj_label})")

        # Calculate centroid
        centroid_x = (box[0] + box[2]) / 2
        centroid_y = (box[1] + box[3]) / 2

        # Create object data
        self.tracked_object = {
            "id": obj_id,
            "label": obj_label,
            "box": box,
            "centroid": (centroid_x, centroid_y),
            "frame_time": frame_time,
            "is_initial_frame": True,
        }

        # Clear history and add initial frame
        self.tracked_object_history.clear()
        self.tracked_object_history.append(self.tracked_object.copy())

        # Calculate initial metrics
        self._calculate_tracked_object_metrics(self.tracked_object, frame_width, frame_height)

        # Calculate initial movement
        pan, tilt, _ = self.calculate_movement(frame_width, frame_height, [box])

        # Get zoom amount
        zoom = self._get_zoom_amount(
            frame_width, frame_height, box, box, 0, debug_zoom=False
        )

        # Enqueue movement
        self._enqueue_move(pan, tilt, zoom, frame_time)

        log_event(logger, "info", f"Started tracking object {obj_id} at {box}", event_type="tracking_start")

    def update_tracked_object(
        self,
        obj_id: str,
        box: Tuple[float, float, float, float],
        frame_time: float,
        frame_width: int,
        frame_height: int,
        velocity: Optional[np.ndarray] = None,
    ) -> None:
        """
        Update tracking for an existing object.

        Args:
            obj_id: ID of the tracked object
            box: Updated bounding box
            frame_time: Current frame timestamp
            frame_width: Width of the frame
            frame_height: Height of the frame
            velocity: Optional velocity estimate
        """
        if self.tracked_object is None or self.tracked_object.get("id") != obj_id:
            logger.warning(f"Cannot update - not tracking object {obj_id}")
            return

        # Don't process duplicate frames
        if self.tracked_object_history and self.tracked_object_history[-1].get("frame_time") == frame_time:
            return

        # Calculate centroid
        centroid_x = (box[0] + box[2]) / 2
        centroid_y = (box[1] + box[3]) / 2

        # Update object data
        obj_data = {
            "id": obj_id,
            "label": self.tracked_object.get("label", "unknown"),
            "box": box,
            "centroid": (centroid_x, centroid_y),
            "frame_time": frame_time,
        }

        if velocity is not None:
            obj_data["velocity"] = velocity

        # Add to history
        self.tracked_object_history.append(obj_data.copy())
        self.tracked_object = obj_data

        # Update metrics
        self._calculate_tracked_object_metrics(obj_data, frame_width, frame_height)

        # Check if PTZ is currently moving
        if self.ptz_moving_at_frame_time(frame_time):
            logger.debug(f"PTZ moving at frame time {frame_time}, skipping movement calculation")
            return

        # Check if object is centered enough
        if self.tracked_object_metrics.get("below_distance_threshold", False):
            logger.debug(f"Object {obj_id} is centered, no pan/tilt needed")
            # Still try zooming if needed
            zoom = self._get_zoom_amount(
                frame_width, frame_height, box, box, 0, debug_zoom=False
            )
            if zoom != 0:
                self._enqueue_move(0, 0, zoom, frame_time)
        else:
            logger.debug(f"Object {obj_id} needs repositioning")

            # Calculate movement with prediction if we have velocity and coefficients
            pan, tilt, _ = self.calculate_movement(frame_width, frame_height, [box])

            predicted_box = box
            predicted_time = 0.0

            if self.move_coefficients and "velocity" in obj_data:
                # Predict movement time
                predicted_time = self._predict_movement_time(pan, tilt)

                # Calculate predicted box position
                if "velocity" in self.tracked_object_metrics and np.any(
                    self.tracked_object_metrics["velocity"]
                ):
                    camera_fps = 15.0
                    current_box = np.array(box)
                    velocity_array = self.tracked_object_metrics["velocity"]
                    predicted_box_array = current_box + camera_fps * predicted_time * velocity_array
                    predicted_box = tuple(np.round(predicted_box_array).astype(int))

                    # Recalculate pan/tilt with predicted position
                    predicted_centroid_x = (predicted_box[0] + predicted_box[2]) / 2
                    predicted_centroid_y = (predicted_box[1] + predicted_box[3]) / 2

                    pan = ((predicted_centroid_x / frame_width) - 0.5) * 2
                    tilt = (0.5 - (predicted_centroid_y / frame_height)) * 2

                    logger.debug(f"Original box: {box}, Predicted box: {predicted_box}")

            # Get zoom amount
            zoom = self._get_zoom_amount(
                frame_width, frame_height, box, predicted_box, predicted_time, debug_zoom=False
            )

            # Enqueue movement
            self._enqueue_move(pan, tilt, zoom, frame_time)

    def _calculate_tracked_object_metrics(
        self, obj_data: Dict[str, Any], frame_width: int, frame_height: int, camera_fps: float = 15.0
    ) -> None:
        """Calculate and update metrics for the currently tracked object."""
        frame_area = frame_width * frame_height

        # Filter history to recent time window
        current_time = obj_data["frame_time"]
        time_window = 1.5  # seconds
        history = [
            entry
            for entry in self.tracked_object_history
            if not entry.get("is_initial_frame", False)
            and current_time - entry["frame_time"] <= time_window
        ]

        if not history:
            history = [self.tracked_object_history[-1]] if self.tracked_object_history else []

        # Calculate areas as squares of largest dimension
        areas = [
            {
                "frame_time": entry["frame_time"],
                "box": entry["box"],
                "area": max(entry["box"][2] - entry["box"][0], entry["box"][3] - entry["box"][1])
                ** 2,
            }
            for entry in history
        ]

        filtered_areas = self._remove_outliers(areas) if len(areas) > 3 else areas

        # Filter entries not touching frame edge
        filtered_areas_not_touching_edge = [
            entry
            for entry in filtered_areas
            if self._touching_frame_edges(frame_width, frame_height, entry["box"]) == 0
        ]

        # Calculate regression for area change predictions
        if filtered_areas_not_touching_edge:
            X = np.array([item["frame_time"] for item in filtered_areas_not_touching_edge])
            y = np.array([item["area"] for item in filtered_areas_not_touching_edge])

            self.tracked_object_metrics["area_coefficients"] = np.linalg.lstsq(
                X.reshape(-1, 1), y, rcond=None
            )[0]
        else:
            self.tracked_object_metrics["area_coefficients"] = np.array([0])

        # Calculate weighted average area
        weights = np.arange(1, len(filtered_areas) + 1)
        weighted_area = np.average([item["area"] for item in filtered_areas], weights=weights)

        self.tracked_object_metrics["target_box"] = (
            weighted_area / frame_area
        ) ** self.zoom_factor

        if "original_target_box" not in self.tracked_object_metrics:
            self.tracked_object_metrics["original_target_box"] = self.tracked_object_metrics[
                "target_box"
            ]

        # Calculate velocity if available
        if "velocity" in obj_data:
            (
                self.tracked_object_metrics["valid_velocity"],
                self.tracked_object_metrics["velocity"],
            ) = self._get_valid_velocity(
                obj_data["velocity"], frame_width, frame_height, camera_fps
            )
        else:
            self.tracked_object_metrics["valid_velocity"] = False
            self.tracked_object_metrics["velocity"] = np.zeros((4,))

        # Calculate distance threshold
        self.tracked_object_metrics["distance"] = self._get_distance_threshold(
            frame_width, frame_height, obj_data["box"], self.tracked_object_metrics["valid_velocity"]
        )

        # Check if object is centered
        centroid_x, centroid_y = obj_data.get("centroid", (
            (obj_data["box"][0] + obj_data["box"][2]) / 2,
            (obj_data["box"][1] + obj_data["box"][3]) / 2,
        ))
        centroid_distance = np.linalg.norm([
            centroid_x - frame_width / 2,
            centroid_y - frame_height / 2,
        ])

        logger.debug(f"Centroid distance: {centroid_distance}")

        self.tracked_object_metrics["below_distance_threshold"] = (
            centroid_distance < self.tracked_object_metrics["distance"]
        )

