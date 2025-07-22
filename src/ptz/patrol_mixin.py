import threading
import time
from typing import Any, Dict, Optional, Tuple

from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


class PatrolMixin:
    """Mixin class to add patrol functionality to PTZ cameras.
    
    The implementing class must provide:
    - stop_movement() method
    - absolute_move(x, y, zoom) method
    - _force_reset_tracking_state() method
    """
    
    # Patrol configuration constants
    DEFAULT_PATROL_DWELL_TIME = 2.0
    DEFAULT_OBJECT_FOCUS_DURATION = 3.0
    DEFAULT_TRACKING_COOLDOWN_DURATION = 5.0
    DEFAULT_FOCUS_MAX_ZOOM = 1.0
    DEFAULT_PATROL_GRID_X = 4
    DEFAULT_PATROL_GRID_Y = 3
    
    # Default patrol area
    DEFAULT_PATROL_AREA = {
        'zoom_level': 0.3, 
        'xMin': 0.215444446, 
        'xMax': 0.391888916, 
        'yMin': -0.58170867, 
        'yMax': -1
    }
    
    def add_patrol_functionality(self, patrol_area: Optional[Dict[str, float]] = None) -> None:
        """Add patrol functionality to the PTZ camera."""
        self._init_patrol_area(patrol_area)
        self._init_patrol_state()
        self._init_patrol_tracking()
        self._init_patrol_position_tracking()
        self._init_patrol_cooldown()
        
        # Default grid configuration
        self.configure_patrol_grid(self.DEFAULT_PATROL_GRID_X, self.DEFAULT_PATROL_GRID_Y)
    
    def _init_patrol_area(self, patrol_area: Optional[Dict[str, float]]) -> None:
        """Initialize patrol area configuration."""
        self.patrol_area = patrol_area if patrol_area is not None else self.DEFAULT_PATROL_AREA.copy()
        
    def _init_patrol_state(self) -> None:
        """Initialize basic patrol state variables."""
        self.is_patrolling = False
        self.patrol_thread: Optional[threading.Thread] = None
        self.patrol_x_step = 0.0
        self.patrol_y_step = 0.0
        self.patrol_dwell_time = self.DEFAULT_PATROL_DWELL_TIME
        self.patrol_stop_event = threading.Event()
        self.patrol_direction = "horizontal"
        self.zoom_during_patrol = self.patrol_area.get('zoom_level', 0.3)
        
    def _init_patrol_tracking(self) -> None:
        """Initialize patrol tracking behavior variables."""
        self.patrol_paused = False
        self.patrol_pause_event = threading.Event()
        self.patrol_resume_event = threading.Event()
        self.object_focus_duration = self.DEFAULT_OBJECT_FOCUS_DURATION
        self.object_focus_start_time = 0.0
        self.is_focusing_on_object = False
        self.pre_focus_position: Optional[Dict[str, Any]] = None
        
    def _init_patrol_position_tracking(self) -> None:
        """Initialize patrol position tracking for resume functionality."""
        self.current_patrol_x_step = 0
        self.current_patrol_y_step = 0
        self.current_patrol_left_to_right = True
        self.current_patrol_top_to_bottom = True
        self.patrol_position_before_tracking: Optional[Dict[str, Any]] = None
        self.position_return_in_progress = False
        
    def _init_patrol_cooldown(self) -> None:
        """Initialize patrol cooldown settings."""
        self.patrol_tracking_cooldown_duration = self.DEFAULT_TRACKING_COOLDOWN_DURATION
        self.tracking_cooldown_end_time = 0.0
        self.is_in_tracking_cooldown = False
        self.patrol_tracking_cooldown_steps = 2  # Legacy compatibility
        self.focus_max_zoom = self.DEFAULT_FOCUS_MAX_ZOOM

    def configure_patrol_grid(self, x_positions: int = 4, y_positions: int = 3) -> None:
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

    def start_patrol(self, direction: str = "horizontal") -> None:
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
        
    def stop_patrol(self) -> None:
        """Stop the patrol function."""
        if not self.is_patrolling:
            return
            
        self.patrol_stop_event.set()
        if self.patrol_thread:
            self.patrol_thread.join(timeout=5.0)
        self.is_patrolling = False
        if hasattr(self, 'stop_movement'):
            self.stop_movement()
        log_event(logger, "info", "Patrol stopped", event_type="info")

    def _patrol_routine(self) -> None:
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

    def _clamp_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Ensure coordinates stay within patrol area bounds."""
        x = max(self.patrol_area['xMin'], min(self.patrol_area['xMax'], x))
        y = max(self.patrol_area['yMax'], min(self.patrol_area['yMin'], y))
        return x, y

    def _horizontal_patrol(self, zoom_level: float) -> None:
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
                    if hasattr(self, 'absolute_move'):
                        self.absolute_move(current_x, current_y, zoom_level)
                    
                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()
                    
                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()
                
                # Alternate direction for next row
                self.current_patrol_left_to_right = not self.current_patrol_left_to_right
            
            log_event(logger, "info", "Horizontal patrol cycle complete, restarting from beginning", event_type="patrol_cycle_complete")

    def _vertical_patrol(self, zoom_level: float) -> None:
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
                    if hasattr(self, 'absolute_move'):
                        self.absolute_move(current_x, current_y, zoom_level)
                    
                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()
                    
                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()
                
                # Alternate direction for next column
                self.current_patrol_top_to_bottom = not self.current_patrol_top_to_bottom
            
            log_event(logger, "info", "Vertical patrol cycle complete, restarting from beginning", event_type="patrol_cycle_complete")

    def _patrol_dwell_with_pause_check(self) -> None:
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
                    if hasattr(self, '_force_reset_tracking_state'):
                        getattr(self, '_force_reset_tracking_state')()
                    break
            
            time.sleep(0.1)  # Short sleep to avoid busy waiting

    def _advance_patrol_step(self) -> None:
        """Called when patrol advances to next position - kept for compatibility."""
        pass

    def is_patrol_active(self) -> bool:
        """Returns whether patrol is currently active."""
        return self.is_patrolling

    def get_patrol_direction(self) -> str:
        """Returns the current patrol direction."""
        if not hasattr(self, 'patrol_direction'):
            return "horizontal"
        return self.patrol_direction

    def get_patrol_grid_info(self) -> Dict[str, Any]:
        """Returns current patrol grid configuration."""
        if not hasattr(self, 'patrol_x_positions'):
            return {"x_positions": 4, "y_positions": 3}
        return {
            "x_positions": self.patrol_x_positions,
            "y_positions": self.patrol_y_positions,
            "x_step": self.patrol_x_step,
            "y_step": self.patrol_y_step
        }

    def set_patrol_parameters(self, x_positions: Optional[int] = None, y_positions: Optional[int] = None, 
                            dwell_time: Optional[float] = None, direction: Optional[str] = None, 
                            object_focus_duration: Optional[float] = None, tracking_cooldown_duration: Optional[float] = None, 
                            focus_max_zoom: Optional[float] = None) -> None:
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
        
        # Update zoom_during_patrol from patrol_area if available
        if hasattr(self, 'patrol_area') and 'zoom_level' in self.patrol_area:
            zoom_level = self.patrol_area['zoom_level']
            if 0.0 <= zoom_level <= 1.0:
                self.zoom_during_patrol = zoom_level
            else:
                log_event(logger, "warning", f"Zoom level {zoom_level} from patrol_area is outside allowed range [0.0, 1.0]", event_type="warning")
                
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

    def get_patrol_status(self) -> Dict[str, Any]:
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

    def set_patrol_area(self, patrol_area: Dict[str, float]) -> None:
        """Set the patrol area boundaries."""
        self.patrol_area = patrol_area
        # Recalculate steps based on new area
        if hasattr(self, 'patrol_x_positions'):
            self.configure_patrol_grid(self.patrol_x_positions, self.patrol_y_positions)