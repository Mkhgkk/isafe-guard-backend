import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .base import ONVIFCameraBase
from .patrol_mixin import PatrolMixin
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)



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
        
    def _init_movement_state(self) -> None:
        """Initialize movement state variables."""
        # Timing
        self.last_move_time: float = time.time()
        self.last_detection_time: float = time.time()
        
        # Default/home position
        self.home_pan: float = 0
        self.home_tilt: float = 0
        self.home_zoom: float = self.min_zoom
        
        # Movement state
        self.is_moving: bool = False
        self.is_at_default_position: bool = False
        
        # PTZ metrics
        self.ptz_metrics: Dict[str, float] = {
            "zoom_level": self.min_zoom,
        }
        
        self.calibrating: bool = False
        
        # Initialize movement queue
        self._init_movement_queue()
        
    def _init_movement_queue(self) -> None:
        """Initialize movement queue and processing thread."""
        self.move_queue: queue.Queue[Tuple[float, float, float]] = queue.Queue()
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
        if self.is_focusing_on_object and current_time - self.object_focus_start_time >= 1.0:
            log_event(logger, "info", "Object lost during focus - ending tracking", event_type="object_lost")
            self._end_object_focus_with_cooldown()
    
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

    def _predict_movement_time(self, pan: float, tilt: float) -> float:
        """Predict movement time (placeholder for future implementation)."""
        return abs(pan) + abs(tilt)

