import threading
import time
from typing import Any, Dict, Optional, Tuple

from utils.logging_config import get_logger, log_event
from events.api import emit_custom_event

logger = get_logger(__name__)


class PatrolMixin:
    """Mixin class to add patrol functionality to PTZ cameras.

    The implementing class must provide:
    - stop_movement() method
    - absolute_move(x, y, zoom) method
    - _force_reset_tracking_state() method
    """

    # Patrol configuration constants
    DEFAULT_PATROL_DWELL_TIME = 30.0
    DEFAULT_OBJECT_FOCUS_DURATION = 10.0
    DEFAULT_MIN_OBJECT_FOCUS_DURATION = 5.0  # Minimum focus time even if object lost
    DEFAULT_TRACKING_COOLDOWN_DURATION = 5.0
    DEFAULT_FOCUS_MAX_ZOOM = 1.0
    DEFAULT_PATROL_GRID_X = 4
    DEFAULT_PATROL_GRID_Y = 3
    DEFAULT_HOME_REST_DURATION = 30.0  # 10 seconds rest at home position
    DEFAULT_PATTERN_REST_CYCLES = 1  # Rest after every N pattern cycles

    # Default patrol area
    DEFAULT_PATROL_AREA = {
        "zoom_level": 0.3,
        "xMin": 0.215444446,
        "xMax": 0.391888916,
        "yMin": -0.58170867,
        "yMax": -1,
    }

    def add_patrol_functionality(
        self, patrol_area: Optional[Dict[str, float]] = None
    ) -> None:
        """Add patrol functionality to the PTZ camera."""
        self._init_patrol_area(patrol_area)
        self._init_patrol_state()
        self._init_patrol_tracking()
        self._init_patrol_position_tracking()
        self._init_patrol_cooldown()

        # Default grid configuration
        self.configure_patrol_grid(
            self.DEFAULT_PATROL_GRID_X, self.DEFAULT_PATROL_GRID_Y
        )

    def _init_patrol_area(self, patrol_area: Optional[Dict[str, float]]) -> None:
        """Initialize patrol area configuration."""
        self.patrol_area = (
            patrol_area if patrol_area is not None else self.DEFAULT_PATROL_AREA.copy()
        )

    def _init_patrol_state(self) -> None:
        """Initialize basic patrol state variables."""
        self.is_patrolling = False
        self.patrol_thread: Optional[threading.Thread] = None
        self.patrol_x_step = 0.0
        self.patrol_y_step = 0.0
        self.patrol_dwell_time = self.DEFAULT_PATROL_DWELL_TIME
        self.patrol_stop_event = threading.Event()
        self.patrol_direction = "horizontal"
        self.patrol_mode = "pattern"  # "grid" or "pattern" - defaults to grid
        self.custom_patrol_pattern: Optional[list] = None  # Stores custom waypoints
        self.pattern_cycle_count = 0  # Track number of complete pattern cycles
        self.pattern_rest_cycles = (
            self.DEFAULT_PATTERN_REST_CYCLES
        )  # Rest after N cycles
        self.pattern_focused_waypoints: set = (
            set()
        )  # Track which waypoints focused in current cycle
        self.is_at_pattern_waypoint = False  # True only when dwelling at a waypoint
        self.zoom_during_patrol = self.patrol_area.get("zoom_level", 0.3)
        self.home_rest_duration = (
            self.DEFAULT_HOME_REST_DURATION
        )  # Rest time at home (default 10 seconds)
        self.is_resting_at_home = (
            False  # Flag to indicate when patrol is in rest period
        )
        self.preview_stop_event = threading.Event()  # Stop event for preview
        self.is_previewing = False  # Flag to indicate preview is running
        self.waypoint_arrival_time = 0.0  # Track when we arrived at current waypoint
        self.min_waypoint_dwell_before_focus = (
            5.0  # Minimum seconds at waypoint before focus allowed
        )

    def _init_patrol_tracking(self) -> None:
        """Initialize patrol tracking behavior variables."""
        self.patrol_paused = False
        self.patrol_pause_event = threading.Event()
        self.patrol_resume_event = threading.Event()
        self.object_focus_duration = self.DEFAULT_OBJECT_FOCUS_DURATION
        self.min_object_focus_duration = self.DEFAULT_MIN_OBJECT_FOCUS_DURATION
        self.object_focus_start_time = 0.0
        self.is_focusing_on_object = False
        self.pre_focus_position: Optional[Dict[str, Any]] = None
        self.enable_focus_during_patrol = False  # Disable focus by default

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
        if not hasattr(self, "patrol_area"):
            self.add_patrol_functionality()

        x_range = self.patrol_area["xMax"] - self.patrol_area["xMin"]
        y_range = abs(self.patrol_area["yMax"] - self.patrol_area["yMin"])

        # Calculate step sizes based on number of positions
        self.patrol_x_step = x_range / (x_positions - 1) if x_positions > 1 else 0
        self.patrol_y_step = y_range / (y_positions - 1) if y_positions > 1 else 0

        self.patrol_x_positions = x_positions
        self.patrol_y_positions = y_positions

        log_event(
            logger,
            "info",
            f"Patrol configured for {x_positions}x{y_positions} grid",
            event_type="patrol_grid_configured",
        )
        log_event(
            logger,
            "info",
            f"X step size: {self.patrol_x_step:.6f}, Y step size: {self.patrol_y_step:.6f}",
            event_type="patrol_step_size",
        )

    def start_patrol(self, direction: str = "horizontal", mode: str = "grid") -> None:
        """Start the patrol function in a separate thread.

        Args:
            direction: "horizontal" or "vertical" (only used for grid mode)
            mode: "grid" or "pattern" - determines patrol type
        """
        if not hasattr(self, "patrol_area"):
            self.add_patrol_functionality()

        # Validate mode
        if mode not in ["grid", "pattern"]:
            log_event(
                logger,
                "warning",
                f"Invalid patrol mode: {mode}. Using 'grid'.",
                event_type="warning",
            )
            mode = "grid"

        # For pattern mode, check if custom pattern is set
        if mode == "pattern":
            if (
                not hasattr(self, "custom_patrol_pattern")
                or not self.custom_patrol_pattern
            ):
                log_event(
                    logger,
                    "error",
                    "Cannot start pattern patrol: no custom pattern set",
                    event_type="error",
                )
                return
            if len(self.custom_patrol_pattern) < 2:
                log_event(
                    logger,
                    "error",
                    f"Cannot start pattern patrol: need at least 2 waypoints, got {len(self.custom_patrol_pattern)}",
                    event_type="error",
                )
                return

        # Validate direction for grid mode
        if mode == "grid" and direction not in ["horizontal", "vertical"]:
            log_event(
                logger,
                "warning",
                f"Invalid patrol direction: {direction}. Using 'horizontal'.",
                event_type="warning",
            )
            direction = "horizontal"

        self.patrol_direction = direction
        self.patrol_mode = mode

        if self.is_patrolling:
            self.stop_patrol()

        self.is_patrolling = True
        self.patrol_stop_event.clear()
        self.patrol_thread = threading.Thread(target=self._patrol_routine)
        self.patrol_thread.daemon = True
        self.patrol_thread.start()

        if mode == "grid":
            mode_description = f"{direction} progression"
        else:
            waypoint_count = (
                len(self.custom_patrol_pattern) if self.custom_patrol_pattern else 0
            )
            mode_description = f"custom pattern ({waypoint_count} waypoints)"

        log_event(
            logger,
            "info",
            f"Patrol started in {mode_description} mode",
            event_type="info",
        )

    def stop_patrol(self) -> None:
        """Stop the patrol function."""
        if not self.is_patrolling:
            return

        self.patrol_stop_event.set()
        if self.patrol_thread:
            # Wait up to 15 seconds for the thread to finish
            self.patrol_thread.join(timeout=15.0)

            # Check if thread is still alive after timeout
            if self.patrol_thread.is_alive():
                log_event(
                    logger,
                    "warning",
                    "Patrol thread did not stop within timeout, but stop event is set. Thread will exit soon.",
                    event_type="patrol_stop_timeout"
                )
                # Give it a bit more time - patrol checks stop event every 0.1-0.5 seconds
                self.patrol_thread.join(timeout=5.0)

        self.is_patrolling = False
        if hasattr(self, "stop_movement"):
            self.stop_movement()
        log_event(logger, "info", "Patrol stopped", event_type="info")

    def _patrol_routine(self) -> None:
        """Main patrol routine that implements a scanning pattern."""
        try:
            # Route to appropriate patrol method based on mode
            if self.patrol_mode == "pattern":
                self._custom_pattern_patrol()
            else:
                # Grid mode
                zoom_level = self.zoom_during_patrol
                if self.patrol_direction == "horizontal":
                    self._horizontal_patrol(zoom_level)
                else:
                    self._vertical_patrol(zoom_level)

        except Exception as e:
            log_event(
                logger, "error", f"Error in patrol routine: {e}", event_type="error"
            )
            self.is_patrolling = False

    def _clamp_coordinates(self, x: float, y: float) -> Tuple[float, float]:
        """Ensure coordinates stay within patrol area bounds."""
        x = max(self.patrol_area["xMin"], min(self.patrol_area["xMax"], x))
        y = max(self.patrol_area["yMax"], min(self.patrol_area["yMin"], y))
        return x, y

    def _stop_tracking_for_rest(self) -> None:
        """Stop any ongoing tracking/focusing when patrol cycle completes.

        This method aggressively clears all tracking state to ensure no focusing
        happens during rest periods.
        """
        # Reset focus state
        if hasattr(self, "is_focusing_on_object"):
            self.is_focusing_on_object = False
        if hasattr(self, "object_focus_start_time"):
            self.object_focus_start_time = 0.0

        # Clear tracked object
        if hasattr(self, "tracked_object"):
            self.tracked_object = None

        # Clear any pause/resume events that might trigger focusing
        if hasattr(self, "patrol_pause_event"):
            self.patrol_pause_event.clear()
        if hasattr(self, "patrol_resume_event"):
            self.patrol_resume_event.clear()

        # Reset patrol paused state
        if hasattr(self, "patrol_paused"):
            self.patrol_paused = False

        # Clear movement queue if available
        if hasattr(self, "_clear_movement_queue"):
            try:
                self._clear_movement_queue()
            except Exception as e:
                log_event(
                    logger,
                    "warning",
                    f"Error clearing movement queue: {e}",
                    event_type="warning",
                )

        # Stop any ongoing movements
        if hasattr(self, "stop_movement"):
            try:
                self.stop_movement()
            except Exception as e:
                log_event(
                    logger,
                    "warning",
                    f"Error stopping movement: {e}",
                    event_type="warning",
                )

        log_event(
            logger,
            "info",
            "Stopped all tracking and focusing for patrol rest period",
            event_type="patrol_tracking_stopped",
        )

    def _return_to_home_and_rest(self) -> None:
        """Return camera to home position and rest for configured duration.

        This method:
        1. Stops any ongoing tracking/focusing
        2. Returns camera to home position (non-blocking via thread)
        3. Sets rest flag to pause patrol and tracking
        4. Rests at home for configured duration while ensuring camera stays static
        5. Clears rest flag to resume patrol
        """
        # Stop any ongoing tracking/focusing
        self._stop_tracking_for_rest()

        # Set flag to indicate patrol is resting (blocks tracking and patrol movement)
        self.is_resting_at_home = True

        # Return to home position in separate thread (non-blocking)
        def _return_home_thread():
            """Thread function to return camera to home position."""
            try:
                # Get home position from implementing class (e.g., PTZAutoTracker)
                home_x = getattr(self, "home_pan", 0.0)
                home_y = getattr(self, "home_tilt", 0.0)
                home_zoom = getattr(self, "home_zoom", 0.0)

                log_event(
                    logger,
                    "info",
                    f"Returning to home position: ({home_x:.6f}, {home_y:.6f}, zoom: {home_zoom:.6f})",
                    event_type="patrol_return_home",
                )

                # Stop any ongoing movements first
                if hasattr(self, "stop_movement"):
                    self.stop_movement()

                # Move to home position
                if hasattr(self, "absolute_move"):
                    self.absolute_move(home_x, home_y, home_zoom)

                # Update zoom metrics if available
                if hasattr(self, "ptz_metrics"):
                    self.ptz_metrics["zoom_level"] = home_zoom

                # Mark as at default position
                if hasattr(self, "is_at_default_position"):
                    self.is_at_default_position = True

                log_event(
                    logger,
                    "debug",
                    "Camera moved to home position",
                    event_type="patrol_home_position_reached",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error returning to home position: {e}",
                    event_type="error",
                )

        # Start return home in separate thread (non-blocking)
        home_thread = threading.Thread(target=_return_home_thread)
        home_thread.daemon = True
        home_thread.start()

        # Wait a moment for movement to start
        time.sleep(0.5)

        # Rest at home position (this ensures camera stays static)
        log_event(
            logger,
            "info",
            f"Resting at home position for {self.home_rest_duration:.1f} seconds - patrol and tracking paused",
            event_type="patrol_rest_at_home",
        )
        self._rest_at_position(self.home_rest_duration)

        # Clear rest flag to resume patrol
        self.is_resting_at_home = False
        log_event(
            logger,
            "info",
            "Rest period complete - resuming patrol",
            event_type="patrol_rest_complete",
        )

    def _rest_at_position(self, duration: float) -> None:
        """Rest at current position for specified duration while ensuring camera stays static.

        During rest period:
        - Checks for stop events every 0.5 seconds
        - Prevents any tracking or focusing (aggressively)
        - Clears any pause events that might trigger tracking
        - Ensures camera remains completely static at home position
        """
        rest_start = time.time()

        while time.time() - rest_start < duration:
            if self.patrol_stop_event.is_set():
                log_event(
                    logger,
                    "info",
                    "Patrol stop requested during rest period",
                    event_type="patrol_rest_interrupted",
                )
                break

            # Ensure no tracking is happening during rest
            if hasattr(self, "is_focusing_on_object") and self.is_focusing_on_object:
                self.is_focusing_on_object = False
                log_event(
                    logger,
                    "warning",
                    "Forcibly disabled tracking during rest period",
                    event_type="patrol_rest_tracking_disabled",
                )

            # Clear any pause events that might have been set
            if hasattr(self, "patrol_pause_event") and self.patrol_pause_event.is_set():
                self.patrol_pause_event.clear()
                log_event(
                    logger,
                    "warning",
                    "Cleared pause event during rest period - tracking not allowed",
                    event_type="patrol_rest_pause_cleared",
                )

            # Ensure tracked object is cleared
            if hasattr(self, "tracked_object") and self.tracked_object is not None:
                self.tracked_object = None
                log_event(
                    logger,
                    "warning",
                    "Cleared tracked object during rest period",
                    event_type="patrol_rest_object_cleared",
                )

            # Ensure camera stays stopped
            if hasattr(self, "is_moving") and self.is_moving:
                if hasattr(self, "stop_movement"):
                    self.stop_movement()
                log_event(
                    logger,
                    "warning",
                    "Stopped movement during rest period",
                    event_type="patrol_rest_movement_stopped",
                )

            time.sleep(0.5)  # Check every 0.5 seconds

    def _horizontal_patrol(self, zoom_level: float) -> None:
        """Horizontal progression patrol (snake pattern) with object focus capability.
        Completes one cycle, returns to home position, rests for 1 minute, then repeats.
        """
        while not self.patrol_stop_event.is_set():
            self.current_patrol_left_to_right = True

            # Complete one full patrol cycle
            for y_step in range(self.patrol_y_positions):
                if self.patrol_stop_event.is_set():
                    break

                self.current_patrol_y_step = y_step
                current_y = self.patrol_area["yMin"] - (y_step * self.patrol_y_step)
                current_y = max(self.patrol_area["yMax"], current_y)

                # Determine x positions for this row
                x_positions = list(range(self.patrol_x_positions))
                if not self.current_patrol_left_to_right:
                    x_positions.reverse()

                for x_step in x_positions:
                    if self.patrol_stop_event.is_set():
                        break

                    self.current_patrol_x_step = x_step
                    current_x = self.patrol_area["xMin"] + (x_step * self.patrol_x_step)
                    current_x = min(self.patrol_area["xMax"], current_x)

                    # Ensure coordinates are within bounds
                    current_x, current_y = self._clamp_coordinates(current_x, current_y)

                    log_event(
                        logger,
                        "debug",
                        f"Horizontal patrol moving to: ({current_x:.6f}, {current_y:.6f})",
                        event_type="patrol_movement",
                    )
                    if hasattr(self, "_enqueue_absolute_move"):
                        self._enqueue_absolute_move(current_x, current_y, zoom_level)
                    elif hasattr(self, "absolute_move"):
                        # Fallback for backward compatibility
                        self.absolute_move(current_x, current_y, zoom_level)

                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()

                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()

                # Alternate direction for next row
                self.current_patrol_left_to_right = (
                    not self.current_patrol_left_to_right
                )

            # Patrol cycle complete - return to home and rest
            if not self.patrol_stop_event.is_set():
                log_event(
                    logger,
                    "info",
                    "Horizontal patrol cycle complete, returning to home position",
                    event_type="patrol_cycle_complete",
                )
                self._return_to_home_and_rest()

    def _vertical_patrol(self, zoom_level: float) -> None:
        """Vertical progression patrol (column pattern) with object focus capability.
        Completes one cycle, returns to home position, rests for 1 minute, then repeats.
        """
        while not self.patrol_stop_event.is_set():
            self.current_patrol_top_to_bottom = True

            # Complete one full patrol cycle
            for x_step in range(self.patrol_x_positions):
                if self.patrol_stop_event.is_set():
                    break

                self.current_patrol_x_step = x_step
                current_x = self.patrol_area["xMin"] + (x_step * self.patrol_x_step)
                current_x = min(self.patrol_area["xMax"], current_x)

                # Determine y positions for this column
                y_positions = list(range(self.patrol_y_positions))
                if not self.current_patrol_top_to_bottom:
                    y_positions.reverse()

                for y_step in y_positions:
                    if self.patrol_stop_event.is_set():
                        break

                    self.current_patrol_y_step = y_step
                    current_y = self.patrol_area["yMin"] - (y_step * self.patrol_y_step)
                    current_y = max(self.patrol_area["yMax"], current_y)

                    # Ensure coordinates are within bounds
                    current_x, current_y = self._clamp_coordinates(current_x, current_y)

                    log_event(
                        logger,
                        "debug",
                        f"Vertical patrol moving to: ({current_x:.6f}, {current_y:.6f})",
                        event_type="patrol_movement",
                    )
                    if hasattr(self, "_enqueue_absolute_move"):
                        self._enqueue_absolute_move(current_x, current_y, zoom_level)
                    elif hasattr(self, "absolute_move"):
                        # Fallback for backward compatibility
                        self.absolute_move(current_x, current_y, zoom_level)

                    # Advance patrol step (for compatibility)
                    self._advance_patrol_step()

                    # Wait at position, but check for pause events
                    self._patrol_dwell_with_pause_check()

                # Alternate direction for next column
                self.current_patrol_top_to_bottom = (
                    not self.current_patrol_top_to_bottom
                )

            # Patrol cycle complete - return to home and rest
            if not self.patrol_stop_event.is_set():
                log_event(
                    logger,
                    "info",
                    "Vertical patrol cycle complete, returning to home position",
                    event_type="patrol_cycle_complete",
                )
                self._return_to_home_and_rest()

    def _custom_pattern_patrol(self) -> None:
        """Custom pattern patrol that loops through predefined waypoints continuously.
        Includes periodic rest periods to prevent tracking interference during movement.
        Rests at home position after every N cycles (configurable via pattern_rest_cycles).
        """
        if not self.custom_patrol_pattern or len(self.custom_patrol_pattern) < 2:
            log_event(
                logger,
                "error",
                "Cannot execute custom pattern patrol: invalid pattern",
                event_type="error",
            )
            self.is_patrolling = False
            return

        log_event(
            logger,
            "info",
            f"Starting continuous custom pattern patrol with {len(self.custom_patrol_pattern)} waypoints (rest after every {self.pattern_rest_cycles} cycles)",
            event_type="patrol_start",
        )

        # Reset cycle count when starting patrol
        self.pattern_cycle_count = 0

        while not self.patrol_stop_event.is_set():
            self.pattern_cycle_count += 1

            # Reset focus tracking for new cycle - each waypoint can focus once per cycle
            self.pattern_focused_waypoints.clear()

            log_event(
                logger,
                "debug",
                f"Custom pattern patrol cycle {self.pattern_cycle_count} starting (focus tracking reset)",
                event_type="patrol_cycle_start",
            )

            # Loop through all waypoints continuously
            for waypoint_index, waypoint in enumerate(self.custom_patrol_pattern):
                if self.patrol_stop_event.is_set():
                    break

                # Extract coordinates
                current_x = waypoint.get("x", 0.0)
                current_y = waypoint.get("y", 0.0)
                current_zoom = waypoint.get("z", 0.0)

                log_event(
                    logger,
                    "debug",
                    f"Custom pattern patrol moving to waypoint {waypoint_index + 1}/{len(self.custom_patrol_pattern)} (cycle {self.pattern_cycle_count}): ({current_x:.6f}, {current_y:.6f}, zoom: {current_zoom:.6f})",
                    event_type="patrol_movement",
                )

                # Move to waypoint (use queued movement for non-blocking execution)
                if hasattr(self, "_enqueue_absolute_move"):
                    self._enqueue_absolute_move(current_x, current_y, current_zoom)
                elif hasattr(self, "absolute_move"):
                    # Fallback for backward compatibility
                    self.absolute_move(current_x, current_y, current_zoom)

                # Update current waypoint index for tracking
                if hasattr(self, "current_patrol_waypoint_index"):
                    self.current_patrol_waypoint_index = waypoint_index

                # Mark that we're now at a waypoint (enables focusing)
                self.is_at_pattern_waypoint = True

                # Record arrival time at this waypoint for focus delay enforcement
                self.waypoint_arrival_time = time.time()

                # Wait at position - focusing can only happen during this dwell period
                self._patrol_dwell_with_pause_check_pattern(waypoint_index)

                # Mark that we're leaving the waypoint (disables focusing during movement)
                self.is_at_pattern_waypoint = False

            # Cycle complete - check if it's time to rest
            if not self.patrol_stop_event.is_set():
                log_event(
                    logger,
                    "debug",
                    f"Custom pattern patrol cycle {self.pattern_cycle_count} complete",
                    event_type="patrol_cycle_complete",
                )

                # Rest after every N cycles to avoid tracking interference during movement
                if self.pattern_cycle_count % self.pattern_rest_cycles == 0:
                    log_event(
                        logger,
                        "info",
                        f"Pattern patrol completed {self.pattern_cycle_count} cycles, returning to home for rest",
                        event_type="patrol_rest_scheduled",
                    )
                    self._return_to_home_and_rest()

    def _patrol_dwell_with_pause_check(self) -> None:
        """Dwell at patrol position while checking for pause/resume events - simplified.
        Used by grid patrol mode.
        """
        dwell_start = time.time()

        while time.time() - dwell_start < self.patrol_dwell_time:
            if self.patrol_stop_event.is_set():
                break

            # NEVER allow focus during rest periods
            if getattr(self, "is_resting_at_home", False):
                # Clear pause event if somehow set during rest
                if self.patrol_pause_event.is_set():
                    self.patrol_pause_event.clear()
                time.sleep(0.1)
                continue

            # Check if patrol should pause for object focus
            if self.patrol_pause_event.is_set():
                # Safety check: verify focus is still allowed (defense in depth)
                if not self.can_focus_during_patrol():
                    self.patrol_pause_event.clear()
                    time.sleep(0.1)
                    continue

                log_event(
                    logger,
                    "debug",
                    "Patrol paused for object focus",
                    event_type="patrol_pause",
                )

                # Wait for resume signal with timeout
                resume_signaled = self.patrol_resume_event.wait(
                    timeout=30.0
                )  # 30 second max wait

                if resume_signaled:
                    log_event(
                        logger,
                        "debug",
                        "Patrol resume signal received",
                        event_type="patrol_resume_signal",
                    )
                    self.patrol_resume_event.clear()
                    # Continue dwell loop until full patrol_dwell_time is reached
                    log_event(
                        logger,
                        "debug",
                        "Continuing dwell until full dwell time reached",
                        event_type="patrol_dwell_continue",
                    )
                else:
                    log_event(
                        logger,
                        "warning",
                        "Patrol resume timeout - forcing resume",
                        event_type="patrol_resume_timeout",
                    )
                    if hasattr(self, "_force_reset_tracking_state"):
                        getattr(self, "_force_reset_tracking_state")()
                    # Continue dwell despite timeout for consistent behavior
                    log_event(
                        logger,
                        "debug",
                        "Continuing dwell despite timeout",
                        event_type="patrol_dwell_continue_timeout",
                    )

            time.sleep(0.1)  # Short sleep to avoid busy waiting

    def _patrol_dwell_with_pause_check_pattern(self, waypoint_index: int) -> None:
        """Dwell at pattern waypoint with focus tracking - one focus per waypoint per cycle.

        Args:
            waypoint_index: Index of current waypoint in pattern
        """
        dwell_start = time.time()
        min_dwell_before_focus = getattr(self, "min_waypoint_dwell_before_focus", 5.0)
        min_absolute_dwell_time = min_dwell_before_focus

        # Safety check: Ensure patrol_dwell_time is at least as long as min_dwell_before_focus
        if self.patrol_dwell_time < min_absolute_dwell_time:
            log_event(
                logger,
                "warning",
                f"patrol_dwell_time ({self.patrol_dwell_time}s) < min_waypoint_dwell_before_focus ({min_absolute_dwell_time}s). Auto-adjusting to {min_absolute_dwell_time}s",
                event_type="patrol_dwell_time_adjusted",
            )
            self.patrol_dwell_time = min_absolute_dwell_time

        # Check if this waypoint has already focused in this cycle
        has_focused_this_cycle = waypoint_index in self.pattern_focused_waypoints

        while time.time() - dwell_start < self.patrol_dwell_time:
            if self.patrol_stop_event.is_set():
                break

            # NEVER allow focus during rest periods - absolute priority
            if getattr(self, "is_resting_at_home", False):
                # Clear pause event if somehow set during rest
                if self.patrol_pause_event.is_set():
                    self.patrol_pause_event.clear()
                time.sleep(0.1)
                continue

            # Calculate time since arriving at waypoint
            time_at_waypoint = time.time() - getattr(self, "waypoint_arrival_time", 0.0)

            # Check if patrol should pause for object focus
            # Conditions: at waypoint, not focused this cycle, sufficient dwell time, focus enabled
            if (
                self.patrol_pause_event.is_set()
                and self.is_at_pattern_waypoint
                and not has_focused_this_cycle
                and time_at_waypoint >= min_dwell_before_focus
                and self.can_focus_during_patrol()
            ):
                log_event(
                    logger,
                    "info",
                    f"Patrol paused at waypoint {waypoint_index + 1} for object focus (first focus this cycle)",
                    event_type="patrol_pause",
                )

                # Mark this waypoint as having focused in this cycle
                self.pattern_focused_waypoints.add(waypoint_index)
                has_focused_this_cycle = True

                # Wait for resume signal with timeout
                resume_signaled = self.patrol_resume_event.wait(
                    timeout=30.0
                )  # 30 second max wait

                if resume_signaled:
                    log_event(
                        logger,
                        "debug",
                        f"Patrol resume signal received at waypoint {waypoint_index + 1}",
                        event_type="patrol_resume_signal",
                    )
                    self.patrol_resume_event.clear()

                    # Resume signal received - continue dwell loop until full patrol_dwell_time is reached
                    # Do NOT break early, as we want to complete the full configured dwell time at each waypoint
                    log_event(
                        logger,
                        "debug",
                        f"Continuing dwell at waypoint {waypoint_index + 1} until full dwell time reached",
                        event_type="patrol_dwell_continue",
                    )
                else:
                    log_event(
                        logger,
                        "warning",
                        f"Patrol resume timeout at waypoint {waypoint_index + 1} - forcing resume",
                        event_type="patrol_resume_timeout",
                    )
                    if hasattr(self, "_force_reset_tracking_state"):
                        getattr(self, "_force_reset_tracking_state")()

                    # Even on timeout, continue dwell until full patrol_dwell_time is reached
                    # This ensures consistent behavior and prevents premature waypoint changes
                    log_event(
                        logger,
                        "debug",
                        f"Continuing dwell at waypoint {waypoint_index + 1} despite timeout",
                        event_type="patrol_dwell_continue_timeout",
                    )

            elif self.patrol_pause_event.is_set():
                # Focus requested but conditions not met - clear and continue
                self.patrol_pause_event.clear()

            time.sleep(0.1)  # Short sleep to avoid busy waiting

    def _advance_patrol_step(self) -> None:
        """Called when patrol advances to next position - kept for compatibility."""
        pass

    def is_patrol_active(self) -> bool:
        """Returns whether patrol is currently active."""
        return self.is_patrolling

    def can_focus_during_patrol(self) -> bool:
        """Check if focusing/tracking is allowed during current patrol state.

        Returns:
            True if focusing is allowed, False otherwise

        Blocking conditions:
        - enable_focus_during_patrol is False
        - Currently in rest period (is_resting_at_home)
        - Pattern mode: not at waypoint, already focused this cycle, or insufficient dwell time
        """
        # Check if focus is disabled globally
        if not getattr(self, "enable_focus_during_patrol", False):
            return False

        # Never allow focus during rest periods
        if getattr(self, "is_resting_at_home", False):
            return False

        # Grid mode always allows focus (after basic checks above)
        patrol_mode = getattr(self, "patrol_mode", "grid")
        if patrol_mode == "grid":
            return True

        # Pattern mode - check specific conditions
        if patrol_mode == "pattern":
            # Must be at a waypoint (not moving between waypoints)
            if not getattr(self, "is_at_pattern_waypoint", False):
                return False

            # Check if current waypoint has already focused this cycle
            current_waypoint = getattr(self, "current_patrol_waypoint_index", 0)
            focused_waypoints = getattr(self, "pattern_focused_waypoints", set())

            if current_waypoint in focused_waypoints:
                return False

            # Check if we've been at the waypoint long enough
            time_at_waypoint = time.time() - getattr(self, "waypoint_arrival_time", 0.0)
            min_dwell_before_focus = getattr(
                self, "min_waypoint_dwell_before_focus", 5.0
            )

            if time_at_waypoint < min_dwell_before_focus:
                return False

            return True

        return True

    def get_patrol_direction(self) -> str:
        """Returns the current patrol direction."""
        if not hasattr(self, "patrol_direction"):
            return "horizontal"
        return self.patrol_direction

    def get_patrol_grid_info(self) -> Dict[str, Any]:
        """Returns current patrol grid configuration."""
        if not hasattr(self, "patrol_x_positions"):
            return {"x_positions": 4, "y_positions": 3}
        return {
            "x_positions": self.patrol_x_positions,
            "y_positions": self.patrol_y_positions,
            "x_step": self.patrol_x_step,
            "y_step": self.patrol_y_step,
        }

    def set_patrol_parameters(
        self,
        x_positions: Optional[int] = None,
        y_positions: Optional[int] = None,
        dwell_time: Optional[float] = None,
        direction: Optional[str] = None,
        object_focus_duration: Optional[float] = None,
        min_object_focus_duration: Optional[float] = None,
        tracking_cooldown_duration: Optional[float] = None,
        focus_max_zoom: Optional[float] = None,
        home_rest_duration: Optional[float] = None,
        pattern_rest_cycles: Optional[int] = None,
        min_waypoint_dwell_before_focus: Optional[float] = None,
        enable_focus_during_patrol: Optional[bool] = None,
    ) -> None:
        """Set patrol parameters.

        Args:
            x_positions: Grid X positions (grid mode only)
            y_positions: Grid Y positions (grid mode only)
            dwell_time: Time to dwell at each waypoint/position (seconds)
            direction: Patrol direction "horizontal" or "vertical" (grid mode only)
            object_focus_duration: Maximum duration to focus on detected objects (seconds)
            min_object_focus_duration: Minimum focus duration even if object is lost (seconds)
            tracking_cooldown_duration: Cooldown after tracking before resuming (seconds)
            focus_max_zoom: Maximum zoom level when focusing on objects
            home_rest_duration: Duration to rest at home position (seconds)
            pattern_rest_cycles: Rest after every N cycles (pattern mode only)
            min_waypoint_dwell_before_focus: Minimum time (seconds) at waypoint before focus allowed (pattern mode only)
            enable_focus_during_patrol: Enable or disable object focus during patrol
        """
        if not hasattr(self, "patrol_area"):
            self.add_patrol_functionality()

        # Update grid configuration if positions are specified
        if x_positions is not None or y_positions is not None:
            current_x = getattr(self, "patrol_x_positions", 4)
            current_y = getattr(self, "patrol_y_positions", 3)
            new_x = x_positions if x_positions is not None else current_x
            new_y = y_positions if y_positions is not None else current_y
            self.configure_patrol_grid(new_x, new_y)

        if dwell_time is not None:
            self.patrol_dwell_time = dwell_time
            # Ensure dwell_time is at least as long as min_waypoint_dwell_before_focus
            if self.patrol_dwell_time < self.min_waypoint_dwell_before_focus:
                log_event(
                    logger,
                    "warning",
                    f"patrol_dwell_time ({self.patrol_dwell_time}s) is less than min_waypoint_dwell_before_focus ({self.min_waypoint_dwell_before_focus}s). Increasing dwell_time to {self.min_waypoint_dwell_before_focus}s",
                    event_type="warning",
                )
                self.patrol_dwell_time = self.min_waypoint_dwell_before_focus

        # Update zoom_during_patrol from patrol_area if available
        if hasattr(self, "patrol_area") and "zoom_level" in self.patrol_area:
            zoom_level = self.patrol_area["zoom_level"]
            if 0.0 <= zoom_level <= 1.0:
                self.zoom_during_patrol = zoom_level
            else:
                log_event(
                    logger,
                    "warning",
                    f"Zoom level {zoom_level} from patrol_area is outside allowed range [0.0, 1.0]",
                    event_type="warning",
                )

        if direction is not None:
            if direction in ["horizontal", "vertical"]:
                self.patrol_direction = direction
            else:
                log_event(
                    logger,
                    "warning",
                    f"Invalid patrol direction: {direction}",
                    event_type="warning",
                )

        if object_focus_duration is not None:
            self.object_focus_duration = max(
                1.0, object_focus_duration
            )  # Minimum 1 second

        if min_object_focus_duration is not None:
            self.min_object_focus_duration = max(
                1.0, min_object_focus_duration
            )  # Minimum 1 second

        if tracking_cooldown_duration is not None:
            self.patrol_tracking_cooldown_duration = max(
                0.0, tracking_cooldown_duration
            )

        if focus_max_zoom is not None:
            self.focus_max_zoom = max(
                0.1, focus_max_zoom
            )  # Set custom focus zoom limit

        if home_rest_duration is not None:
            self.home_rest_duration = max(0.0, home_rest_duration)  # Minimum 0 seconds

        if pattern_rest_cycles is not None:
            self.pattern_rest_cycles = max(1, pattern_rest_cycles)  # Minimum 1 cycle

        if min_waypoint_dwell_before_focus is not None:
            self.min_waypoint_dwell_before_focus = max(
                0.0, min_waypoint_dwell_before_focus
            )  # Minimum 0 seconds
            # Ensure patrol_dwell_time is at least as long as min_waypoint_dwell_before_focus
            if self.patrol_dwell_time < self.min_waypoint_dwell_before_focus:
                log_event(
                    logger,
                    "warning",
                    f"Adjusting patrol_dwell_time from {self.patrol_dwell_time}s to {self.min_waypoint_dwell_before_focus}s to meet minimum waypoint dwell requirement",
                    event_type="warning",
                )
                self.patrol_dwell_time = self.min_waypoint_dwell_before_focus

        if enable_focus_during_patrol is not None:
            self.enable_focus_during_patrol = enable_focus_during_patrol
            log_event(
                logger,
                "info",
                f"Patrol focus {'enabled' if enable_focus_during_patrol else 'disabled'}",
                event_type="patrol_focus_configured",
            )

    def get_patrol_status(self) -> Dict[str, Any]:
        """Get comprehensive patrol status information."""
        current_time = time.time()
        cooldown_remaining = 0
        if (
            self.is_in_tracking_cooldown
            and self.tracking_cooldown_end_time > current_time
        ):
            cooldown_remaining = self.tracking_cooldown_end_time - current_time

        # Get patrol mode specific information
        patrol_mode = getattr(self, "patrol_mode", "grid")
        pattern_info = None
        if patrol_mode == "pattern" and hasattr(self, "custom_patrol_pattern"):
            current_waypoint_idx = getattr(self, "current_patrol_waypoint_index", 0)
            focused_waypoints = getattr(self, "pattern_focused_waypoints", set())
            pattern_info = {
                "waypoint_count": (
                    len(self.custom_patrol_pattern) if self.custom_patrol_pattern else 0
                ),
                "current_waypoint_index": current_waypoint_idx,
                "cycle_count": getattr(self, "pattern_cycle_count", 0),
                "rest_cycles": getattr(
                    self, "pattern_rest_cycles", self.DEFAULT_PATTERN_REST_CYCLES
                ),
                "next_rest_in": getattr(
                    self, "pattern_rest_cycles", self.DEFAULT_PATTERN_REST_CYCLES
                )
                - (
                    getattr(self, "pattern_cycle_count", 0)
                    % getattr(
                        self, "pattern_rest_cycles", self.DEFAULT_PATTERN_REST_CYCLES
                    )
                ),
                "focused_waypoints_this_cycle": len(focused_waypoints),
                "is_at_waypoint": getattr(self, "is_at_pattern_waypoint", False),
                "current_waypoint_can_focus": (
                    current_waypoint_idx not in focused_waypoints
                    and getattr(self, "is_at_pattern_waypoint", False)
                ),
            }

        return {
            "is_patrolling": self.is_patrolling,
            "patrol_mode": patrol_mode,
            "is_focusing_on_object": getattr(self, "is_focusing_on_object", False),
            "is_resting_at_home": getattr(self, "is_resting_at_home", False),
            "patrol_paused": getattr(self, "patrol_paused", False),
            "patrol_direction": self.get_patrol_direction(),
            "grid_info": self.get_patrol_grid_info(),
            "pattern_info": pattern_info,
            "object_focus_duration": getattr(self, "object_focus_duration", 10.0),
            "min_object_focus_duration": getattr(
                self, "min_object_focus_duration", 5.0
            ),
            "dwell_time": self.patrol_dwell_time,
            "min_waypoint_dwell_before_focus": getattr(
                self, "min_waypoint_dwell_before_focus", 5.0
            ),
            "home_rest_duration": getattr(
                self, "home_rest_duration", self.DEFAULT_HOME_REST_DURATION
            ),
            "tracking_cooldown": {
                "is_in_cooldown": getattr(self, "is_in_tracking_cooldown", False),
                "time_remaining": cooldown_remaining,
                "total_cooldown_duration": getattr(
                    self, "patrol_tracking_cooldown_duration", 5.0
                ),
            },
            "current_position": {
                "x_step": getattr(self, "current_patrol_x_step", 0),
                "y_step": getattr(self, "current_patrol_y_step", 0),
                "left_to_right": getattr(self, "current_patrol_left_to_right", True),
                "top_to_bottom": getattr(self, "current_patrol_top_to_bottom", True),
            },
            "stored_position": getattr(self, "patrol_position_before_tracking", None),
            "position_return_in_progress": getattr(
                self, "position_return_in_progress", False
            ),
            "enable_focus_during_patrol": getattr(
                self, "enable_focus_during_patrol", False
            ),
        }

    def set_patrol_area(self, patrol_area: Dict[str, float]) -> None:
        """Set the patrol area boundaries."""
        self.patrol_area = patrol_area
        # Recalculate steps based on new area
        if hasattr(self, "patrol_x_positions"):
            self.configure_patrol_grid(self.patrol_x_positions, self.patrol_y_positions)

    def set_custom_patrol_pattern(self, coordinates: list) -> None:
        """Set a custom patrol pattern with specific waypoints.

        Args:
            coordinates: List of dicts with x, y, z values representing waypoints
        """
        if not coordinates or len(coordinates) < 2:
            log_event(
                logger,
                "warning",
                "Custom patrol pattern requires at least 2 waypoints",
                event_type="warning",
            )
            return

        self.custom_patrol_pattern = coordinates
        log_event(
            logger,
            "info",
            f"Custom patrol pattern set with {len(coordinates)} waypoints",
            event_type="custom_patrol_pattern_set",
        )

    def preview_custom_patrol_pattern(
        self, coordinates: list, stream_id: Optional[str] = None
    ) -> None:
        """Preview a custom patrol pattern by executing it once.

        Args:
            coordinates: List of dicts with x, y, z values representing waypoints
            stream_id: Optional stream identifier for socket event emissions
        """
        if not coordinates or len(coordinates) < 2:
            log_event(
                logger,
                "warning",
                "Preview requires at least 2 waypoints",
                event_type="warning",
            )
            return

        # Stop any previous preview that might be running
        if self.is_previewing:
            log_event(
                logger,
                "info",
                "Stopping previous preview before starting new one",
                event_type="preview_stop_previous",
            )
            self.preview_stop_event.set()
            time.sleep(0.5)  # Give previous preview time to stop

        # Remember if patrol was running so we can resume it after preview
        patrol_was_running = self.is_patrolling
        patrol_mode_before = getattr(self, "patrol_mode", "grid")

        # Temporarily stop patrol if it's running to avoid conflicts
        if patrol_was_running:
            log_event(
                logger,
                "info",
                "Temporarily stopping patrol for preview",
                event_type="preview_pause_patrol",
            )
            self.stop_patrol()

        log_event(
            logger,
            "info",
            f"Starting preview of custom patrol pattern with {len(coordinates)} waypoints",
            event_type="custom_patrol_preview_start",
        )

        # Clear and reset the preview stop event
        self.preview_stop_event.clear()
        self.is_previewing = True

        # Execute the pattern once in a separate thread
        def _preview_pattern():
            try:
                # Emit preview start event
                if stream_id:
                    emit_custom_event(
                        event_name=f"patrol-preview-start-{stream_id}",
                        data={
                            "waypoint_count": len(coordinates),
                        },
                        room=stream_id,
                        broadcast=False,
                    )

                for idx, waypoint in enumerate(coordinates):
                    # Check if preview should stop
                    if self.preview_stop_event.is_set():
                        log_event(
                            logger,
                            "info",
                            f"Preview stopped at waypoint {idx + 1}/{len(coordinates)}",
                            event_type="preview_stopped",
                        )
                        break

                    x = waypoint.get("x", 0.0)
                    y = waypoint.get("y", 0.0)
                    z = waypoint.get("z", 0.0)

                    log_event(
                        logger,
                        "debug",
                        f"Moving to waypoint {idx + 1}/{len(coordinates)}: ({x:.6f}, {y:.6f}, zoom: {z:.6f})",
                        event_type="custom_patrol_waypoint",
                    )

                    # Emit waypoint event
                    if stream_id:
                        emit_custom_event(
                            event_name=f"patrol-preview-waypoint-{stream_id}",
                            data={
                                "waypoint_index": idx,
                                "waypoint_number": idx + 1,
                                "total_waypoints": len(coordinates),
                                "position": {"x": x, "y": y, "z": z},
                            },
                            room=stream_id,
                            broadcast=False,
                        )

                    if hasattr(self, "absolute_move"):
                        self.absolute_move(x, y, z)

                    # Wait at each waypoint, but check for stop event periodically
                    dwell_time = getattr(self, "patrol_dwell_time", 2.0)
                    sleep_interval = 0.5
                    elapsed = 0.0
                    while elapsed < dwell_time:
                        if self.preview_stop_event.is_set():
                            break
                        time.sleep(min(sleep_interval, dwell_time - elapsed))
                        elapsed += sleep_interval

                if not self.preview_stop_event.is_set():
                    log_event(
                        logger,
                        "info",
                        "Custom patrol pattern preview complete",
                        event_type="custom_patrol_preview_complete",
                    )

                    # Emit preview complete event
                    if stream_id:
                        emit_custom_event(
                            event_name=f"patrol-preview-complete-{stream_id}",
                            data={
                                "waypoints_visited": len(coordinates),
                            },
                            room=stream_id,
                            broadcast=False,
                        )

            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error during custom patrol preview: {e}",
                    event_type="error",
                )

                # Emit error event
                if stream_id:
                    emit_custom_event(
                        event_name=f"patrol-preview-error-{stream_id}",
                        data={
                            "error": str(e),
                        },
                        room=stream_id,
                        broadcast=False,
                    )
            finally:
                # Mark preview as finished
                self.is_previewing = False

                # Resume patrol if it was running before
                if patrol_was_running:
                    log_event(
                        logger,
                        "info",
                        f"Resuming {patrol_mode_before} patrol after preview",
                        event_type="preview_resume_patrol",
                    )
                    # Small delay before resuming to avoid movement conflicts
                    time.sleep(1.0)
                    self.start_patrol(mode=patrol_mode_before)

        preview_thread = threading.Thread(target=_preview_pattern)
        preview_thread.daemon = True
        preview_thread.start()
