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
        # min_target_area_ratio: float = 0.03
        # max_target_area_ratio: float = 0.1

        min_target_area_ratio: float = 0.1
        max_target_area_ratio: float = 0.5

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
        
        # Check if we're in cooldown period - ignore objects during cooldown
        if self.is_in_tracking_cooldown:
            if current_time >= self.tracking_cooldown_end_time:
                # Cooldown period ended
                self.is_in_tracking_cooldown = False
                self.tracking_cooldown_end_time = 0.0
                log_event(logger, "info", "Tracking cooldown period ended - objects can be tracked again", event_type="tracking_cooldown_end")
            else:
                # Still in cooldown
                if bboxes is not None and len(bboxes) > 0:
                    remaining_time = self.tracking_cooldown_end_time - current_time
                    log_event(logger, "debug", f"Objects detected but in cooldown period ({remaining_time:.1f}s remaining)", event_type="tracking_cooldown_active")
                return
        
        # Handle object detection
        if bboxes is not None and len(bboxes) > 0:
            if not self.is_focusing_on_object:
                # Start focusing on the object
                log_event(logger, "info", "Object detected during patrol - starting object focus", event_type="object_focus_start")
                self._start_object_focus()
                self.object_focus_start_time = current_time
                
            # Continue focusing on object if within focus duration
            if current_time - self.object_focus_start_time < self.object_focus_duration:
                # Track the object with full sensitivity and FULL ZOOM RANGE
                # Temporarily expand zoom limits for better object tracking
                original_max_zoom = self.max_zoom
                self.max_zoom = getattr(self, 'focus_max_zoom', 1.0)  # Use enhanced zoom limit
                
                pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bboxes)
                
                # Restore original zoom limit
                self.max_zoom = original_max_zoom
                
                if not (pan == 0 and tilt == 0 and zoom == 0):
                    self._enqueue_move(pan, tilt, zoom)
                    
                self.last_move_time = current_time
                self.last_detection_time = current_time
            else:
                # Focus duration exceeded, end tracking
                log_event(logger, "info", "Object focus duration exceeded - ending tracking", event_type="object_focus_timeout")
                self._end_object_focus_with_cooldown()
        else:
            # No objects detected
            if self.is_focusing_on_object:
                # Was focusing on object but it's gone
                if current_time - self.object_focus_start_time >= 1.0:  # Minimum 1 second focus
                    log_event(logger, "info", "Object lost during focus - ending tracking", event_type="object_lost")
                    self._end_object_focus_with_cooldown()

    def _start_object_focus(self):
        """Start focusing on detected object during patrol - simplified."""
        try:
            # Store current patrol position
            self._store_current_patrol_position()
            
            # Set focus state
            self.is_focusing_on_object = True
            self.patrol_paused = True
            
            # Signal patrol thread to pause
            self.patrol_pause_event.set()
            
            log_event(logger, "debug", "Object focus started - patrol paused", event_type="patrol_pause")
            
        except Exception as e:
            log_event(logger, "error", f"Error starting object focus: {e}", event_type="error")
            # Reset state on error
            self.is_focusing_on_object = False
            self.patrol_paused = False

    def _store_current_patrol_position(self):
        """Store the current patrol position to return to after tracking."""
        try:
            # Calculate current coordinates based on patrol grid position
            current_x = self.patrol_area['xMin'] + (self.current_patrol_x_step * self.patrol_x_step)
            current_y = self.patrol_area['yMin'] - (self.current_patrol_y_step * self.patrol_y_step)
            
            # Clamp coordinates to patrol area
            current_x = max(self.patrol_area['xMin'], min(self.patrol_area['xMax'], current_x))
            current_y = max(self.patrol_area['yMax'], min(self.patrol_area['yMin'], current_y))
            
            self.patrol_position_before_tracking = {
                'x_step': self.current_patrol_x_step,
                'y_step': self.current_patrol_y_step,
                'left_to_right': self.current_patrol_left_to_right,
                'top_to_bottom': self.current_patrol_top_to_bottom,
                'x_coord': current_x,
                'y_coord': current_y,
                'zoom': self.zoom_during_patrol
            }
            
            log_event(logger, "debug", f"Stored patrol position: step({self.current_patrol_x_step},{self.current_patrol_y_step}) coord({current_x:.3f},{current_y:.3f})", event_type="patrol_position_stored")
            
        except Exception as e:
            log_event(logger, "error", f"Error storing patrol position: {e}", event_type="error")
            self.patrol_position_before_tracking = None

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

    def _clear_movement_queue(self):
        """Clear all pending movements from the movement queue."""
        try:
            while not self.move_queue.empty():
                try:
                    self.move_queue.get_nowait()
                    self.move_queue.task_done()
                except queue.Empty:
                    break
            log_event(logger, "debug", "Movement queue cleared", event_type="movement_queue_cleared")
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

    def _force_reset_tracking_state(self):
        """Force reset all tracking-related state in case of errors."""
        log_event(logger, "warning", "Force resetting tracking state", event_type="tracking_state_reset")
        
        self.is_focusing_on_object = False
        self.patrol_paused = False
        self.object_focus_start_time = 0.0
        self.patrol_pause_event.clear()
        self.patrol_resume_event.set()
        self.patrol_position_before_tracking = None
        self.is_in_tracking_cooldown = False
        self.tracking_cooldown_end_time = 0.0
        
        # Stop any movements
        try:
            self.stop_movement()
            self._clear_movement_queue()
        except:
            pass

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
        self.patrol_x_step = 0.0  # Will be calculated by configure_patrol_grid
        self.patrol_y_step = 0.0  # Will be calculated by configure_patrol_grid
        self.patrol_dwell_time = 2.0
        self.patrol_stop_event = threading.Event()
        self.patrol_direction = "horizontal"
        self.zoom_during_patrol = self.patrol_area['zMin']
        
        # Patrol tracking behavior
        self.patrol_paused = False
        self.patrol_pause_event = threading.Event()
        self.patrol_resume_event = threading.Event()
        self.object_focus_duration = 3.0  # Default 3 seconds to focus on detected objects during patrol
        self.object_focus_start_time = 0.0
        self.is_focusing_on_object = False
        self.pre_focus_position = None  # Store position before focusing on object
        
        # Patrol position tracking for resume functionality
        self.current_patrol_x_step = 0
        self.current_patrol_y_step = 0
        self.current_patrol_left_to_right = True
        self.current_patrol_top_to_bottom = True
        
        # Object tracking cooldown - ignore objects for N seconds after tracking
        self.patrol_tracking_cooldown_duration = 5.0  # 5 seconds cooldown
        self.tracking_cooldown_end_time = 0.0
        self.is_in_tracking_cooldown = False
        
        # Backward compatibility (in case old variable is referenced elsewhere)
        self.patrol_tracking_cooldown_steps = 2  # Legacy variable for compatibility
        
        # Store patrol position to return to after tracking
        self.patrol_position_before_tracking = None
        self.position_return_in_progress = False  # Track if position return is happening
        
        # Enhanced zoom control for object focus
        self.focus_max_zoom = 1.0  # Allow higher zoom during object focus
        
        # Default grid configuration (4x3 grid)
        self.configure_patrol_grid(4, 3)

    def configure_patrol_grid(self, x_positions=4, y_positions=3):
        """Configure patrol as a grid with specified number of positions."""
        if not hasattr(self, 'patrol_area'):
            self.add_patrol_functionality()
        
        x_range = self.patrol_area['xMax'] - self.patrol_area['xMin']
        y_range = abs(self.patrol_area['yMax'] - self.patrol_area['yMin'])
        
        # Calculate step sizes based on number of positions
        self.patrol_x_step = x_range / (x_positions - 1) if x_positions > 1 else 0
        self.patrol_y_step = y_range / (y_positions - 1) if y_positions > 1 else 0
        
        self.patrol_x_positions = x_positions
        self.patrol_y_positions = y_positions
        
        log_event(logger, "info", f"Patrol configured for {x_positions}x{y_positions} grid", event_type="patrol_grid_configured")
        log_event(logger, "info", f"X step size: {self.patrol_x_step:.6f}, Y step size: {self.patrol_y_step:.6f}", event_type="patrol_step_size")

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

    def _clamp_coordinates(self, x, y):
        """Ensure coordinates stay within patrol area bounds."""
        x = max(self.patrol_area['xMin'], min(self.patrol_area['xMax'], x))
        y = max(self.patrol_area['yMax'], min(self.patrol_area['yMin'], y))
        return x, y

    def _horizontal_patrol(self, zoom_level):
        """Horizontal progression patrol (snake pattern) with object focus capability."""
        while not self.patrol_stop_event.is_set():
            self.current_patrol_left_to_right = True
            
            for y_step in range(self.patrol_y_positions):
                if self.patrol_stop_event.is_set():
                    break
                
                self.current_patrol_y_step = y_step
                current_y = self.patrol_area['yMin'] - (y_step * self.patrol_y_step)
                current_y = max(self.patrol_area['yMax'], current_y)
                
                # Determine x positions for this row
                x_positions = list(range(self.patrol_x_positions))
                if not self.current_patrol_left_to_right:
                    x_positions.reverse()
                
                for x_step in x_positions:
                    if self.patrol_stop_event.is_set():
                        break
                    
                    self.current_patrol_x_step = x_step
                    current_x = self.patrol_area['xMin'] + (x_step * self.patrol_x_step)
                    current_x = min(self.patrol_area['xMax'], current_x)
                    
                    # Ensure coordinates are within bounds
                    current_x, current_y = self._clamp_coordinates(current_x, current_y)
                    
                    log_event(logger, "debug", f"Horizontal patrol moving to: ({current_x:.6f}, {current_y:.6f})", event_type="patrol_movement")
                    self.absolute_move(current_x, current_y, zoom_level)
                    
                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()
                    
                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()
                
                # Alternate direction for next row
                self.current_patrol_left_to_right = not self.current_patrol_left_to_right
            
            log_event(logger, "info", "Horizontal patrol cycle complete, restarting from beginning", event_type="patrol_cycle_complete")

    def _vertical_patrol(self, zoom_level):
        """Vertical progression patrol (column pattern) with object focus capability."""
        while not self.patrol_stop_event.is_set():
            self.current_patrol_top_to_bottom = True
            
            for x_step in range(self.patrol_x_positions):
                if self.patrol_stop_event.is_set():
                    break
                
                self.current_patrol_x_step = x_step
                current_x = self.patrol_area['xMin'] + (x_step * self.patrol_x_step)
                current_x = min(self.patrol_area['xMax'], current_x)
                
                # Determine y positions for this column
                y_positions = list(range(self.patrol_y_positions))
                if not self.current_patrol_top_to_bottom:
                    y_positions.reverse()
                
                for y_step in y_positions:
                    if self.patrol_stop_event.is_set():
                        break
                    
                    self.current_patrol_y_step = y_step
                    current_y = self.patrol_area['yMin'] - (y_step * self.patrol_y_step)
                    current_y = max(self.patrol_area['yMax'], current_y)
                    
                    # Ensure coordinates are within bounds
                    current_x, current_y = self._clamp_coordinates(current_x, current_y)
                    
                    log_event(logger, "debug", f"Vertical patrol moving to: ({current_x:.6f}, {current_y:.6f})", event_type="patrol_movement")
                    self.absolute_move(current_x, current_y, zoom_level)
                    
                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()
                    
                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()
                
                # Alternate direction for next column
                self.current_patrol_top_to_bottom = not self.current_patrol_top_to_bottom
            
            log_event(logger, "info", "Vertical patrol cycle complete, restarting from beginning", event_type="patrol_cycle_complete")

    def _patrol_dwell_with_pause_check(self):
        """Dwell at patrol position while checking for pause/resume events - simplified."""
        dwell_start = time.time()
        
        while time.time() - dwell_start < self.patrol_dwell_time:
            if self.patrol_stop_event.is_set():
                break
                
            # Check if patrol should pause for object focus
            if self.patrol_pause_event.is_set():
                log_event(logger, "debug", "Patrol paused for object focus", event_type="patrol_pause")
                
                # Wait for resume signal with timeout
                resume_signaled = self.patrol_resume_event.wait(timeout=30.0)  # 30 second max wait
                
                if resume_signaled:
                    log_event(logger, "debug", "Patrol resume signal received", event_type="patrol_resume_signal")
                    self.patrol_resume_event.clear()
                    # Exit dwell early to continue patrol
                    break
                else:
                    log_event(logger, "warning", "Patrol resume timeout - forcing resume", event_type="patrol_resume_timeout")
                    self._force_reset_tracking_state()
                    break
            
            time.sleep(0.1)  # Short sleep to avoid busy waiting

    def is_patrol_active(self):
        """Returns whether patrol is currently active."""
        return self.is_patrolling

    def get_patrol_direction(self):
        """Returns the current patrol direction."""
        if not hasattr(self, 'patrol_direction'):
            return "horizontal"
        return self.patrol_direction

    def get_patrol_grid_info(self):
        """Returns current patrol grid configuration."""
        if not hasattr(self, 'patrol_x_positions'):
            return {"x_positions": 4, "y_positions": 3}
        return {
            "x_positions": self.patrol_x_positions,
            "y_positions": self.patrol_y_positions,
            "x_step": self.patrol_x_step,
            "y_step": self.patrol_y_step
        }

    def set_patrol_parameters(self, x_positions=None, y_positions=None, dwell_time=None, 
                            zoom_level=None, direction=None, object_focus_duration=None,
                            tracking_cooldown_duration=None, focus_max_zoom=None):
        """Set patrol parameters."""
        if not hasattr(self, 'patrol_area'):
            self.add_patrol_functionality()
        
        # Update grid configuration if positions are specified
        if x_positions is not None or y_positions is not None:
            current_x = getattr(self, 'patrol_x_positions', 4)
            current_y = getattr(self, 'patrol_y_positions', 3)
            new_x = x_positions if x_positions is not None else current_x
            new_y = y_positions if y_positions is not None else current_y
            self.configure_patrol_grid(new_x, new_y)
        
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
                
        if object_focus_duration is not None:
            self.object_focus_duration = max(1.0, object_focus_duration)  # Minimum 1 second
            
        if tracking_cooldown_duration is not None:
            self.patrol_tracking_cooldown_duration = max(0.0, tracking_cooldown_duration)
            
        if focus_max_zoom is not None:
            self.focus_max_zoom = max(0.1, focus_max_zoom)  # Set custom focus zoom limit

    def get_patrol_status(self):
        """Get comprehensive patrol status information."""
        current_time = time.time()
        cooldown_remaining = 0
        if self.is_in_tracking_cooldown and self.tracking_cooldown_end_time > current_time:
            cooldown_remaining = self.tracking_cooldown_end_time - current_time
            
        return {
            "is_patrolling": self.is_patrolling,
            "is_focusing_on_object": getattr(self, 'is_focusing_on_object', False),
            "patrol_paused": getattr(self, 'patrol_paused', False),
            "patrol_direction": self.get_patrol_direction(),
            "grid_info": self.get_patrol_grid_info(),
            "object_focus_duration": getattr(self, 'object_focus_duration', 3.0),
            "dwell_time": self.patrol_dwell_time,
            "tracking_cooldown": {
                "is_in_cooldown": getattr(self, 'is_in_tracking_cooldown', False),
                "time_remaining": cooldown_remaining,
                "total_cooldown_duration": getattr(self, 'patrol_tracking_cooldown_duration', 5.0)
            },
            "current_position": {
                "x_step": getattr(self, 'current_patrol_x_step', 0),
                "y_step": getattr(self, 'current_patrol_y_step', 0),
                "left_to_right": getattr(self, 'current_patrol_left_to_right', True),
                "top_to_bottom": getattr(self, 'current_patrol_top_to_bottom', True)
            },
            "stored_position": getattr(self, 'patrol_position_before_tracking', None),
            "position_return_in_progress": getattr(self, 'position_return_in_progress', False)
        }

    def set_patrol_area(self, patrol_area):
        """Set the patrol area boundaries."""
        self.patrol_area = patrol_area
        # Recalculate steps based on new area
        if hasattr(self, 'patrol_x_positions'):
            self.configure_patrol_grid(self.patrol_x_positions, self.patrol_y_positions)