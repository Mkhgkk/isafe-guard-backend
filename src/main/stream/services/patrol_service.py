"""Service for managing patrol operations for PTZ camera streams."""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from database import get_database
from marshmallow import ValidationError

from main.shared import streams
from main.stream.validation import PatrolAreaSchema, PatrolPatternSchema
from utils.logging_config import get_logger, log_event


logger = get_logger(__name__)


class PatrolService:
    """Service for managing patrol areas, patterns, and operations."""

    @staticmethod
    def normalize_patrol_coordinates(patrol_area: dict) -> dict:
        """Normalize patrol coordinates to ensure proper ordering.

        Ensures xMin < xMax and yMin < yMax by swapping if necessary.

        Args:
            patrol_area: Dictionary containing patrol area coordinates

        Returns:
            dict: Patrol area with normalized coordinates
        """
        # Create a copy to avoid modifying the original
        normalized = patrol_area.copy()

        # Ensure xMin < xMax
        if normalized.get("xMin", 0) > normalized.get("xMax", 0):
            normalized["xMin"], normalized["xMax"] = (
                normalized["xMax"],
                normalized["xMin"],
            )
            log_event(
                logger,
                "info",
                "Swapped xMin and xMax to ensure xMin < xMax",
                event_type="info",
            )

        # Ensure yMin < yMax
        if normalized.get("yMin", 0) > normalized.get("yMax", 0):
            normalized["yMin"], normalized["yMax"] = (
                normalized["yMax"],
                normalized["yMin"],
            )
            log_event(
                logger,
                "info",
                "Swapped yMin and yMax to ensure yMin < yMax",
                event_type="info",
            )

        return normalized

    @staticmethod
    def save_patrol_area(stream_id: str, patrol_area: dict) -> Dict[str, Any]:
        """Save patrol area to database and update active stream.

        Args:
            stream_id: Stream identifier
            patrol_area: Dictionary containing patrol area coordinates

        Returns:
            dict: Result with status, message, and data
        """
        try:
            db = get_database()

            # Validate patrol area structure
            patrol_area_schema = PatrolAreaSchema()

            try:
                validated_patrol_area = patrol_area_schema.load(patrol_area)
            except ValidationError as e:
                return {
                    "status": "error",
                    "message": "Invalid patrol area data",
                    "errors": e.messages,
                }

            # Normalize coordinates
            validated_patrol_area = PatrolService.normalize_patrol_coordinates(
                validated_patrol_area
            )

            # Check if stream exists in database
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            if not stream_doc:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            # Update patrol area in database
            result = db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"patrol_area": validated_patrol_area}},
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update in-memory stream if it's active
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                video_streaming.ptz_auto_tracker.set_patrol_area(validated_patrol_area)
                log_event(
                    logger,
                    "info",
                    f"Updated patrol area for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Patrol area saved successfully for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Patrol area saved successfully",
                "data": {
                    "stream_id": stream_id,
                    "patrol_area": validated_patrol_area,
                },
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger, "error", f"Error saving patrol area: {e}", event_type="error"
            )
            return {
                "status": "error",
                "message": f"Failed to save patrol area: {str(e)}",
            }

    @staticmethod
    def get_patrol_area(stream_id: str) -> Dict[str, Any]:
        """Get saved patrol area from database.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and patrol area data
        """
        try:
            db = get_database()

            # Get stream from database
            stream = db.streams.find_one({"stream_id": stream_id})
            if not stream:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            # Get patrol area from stream data
            patrol_area = stream.get("patrol_area")

            if patrol_area is None:
                return {
                    "status": "success",
                    "message": "No patrol area configured for this stream",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_area": None,
                    },
                }

            log_event(
                logger,
                "info",
                f"Retrieved patrol area for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Patrol area retrieved successfully",
                "data": {
                    "stream_id": stream_id,
                    "patrol_area": patrol_area,
                },
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving patrol area: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to retrieve patrol area: {str(e)}",
            }

    @staticmethod
    def save_patrol_pattern(stream_id: str, patrol_pattern: dict) -> Dict[str, Any]:
        """Save patrol pattern to database.

        Args:
            stream_id: Stream identifier
            patrol_pattern: Dictionary containing patrol pattern coordinates

        Returns:
            dict: Result with status, message, and data
        """
        try:
            db = get_database()

            # Validate patrol pattern structure
            patrol_pattern_schema = PatrolPatternSchema()

            try:
                validated_patrol_pattern = patrol_pattern_schema.load(patrol_pattern)
            except ValidationError as e:
                return {
                    "status": "error",
                    "message": "Invalid patrol pattern data",
                    "errors": e.messages,
                }

            # Check if stream exists in database
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            if not stream_doc:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            # Update patrol pattern in database
            result = db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"patrol_pattern": validated_patrol_pattern}},
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            log_event(
                logger,
                "info",
                f"Patrol pattern saved successfully for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Patrol pattern saved successfully",
                "data": {
                    "stream_id": stream_id,
                    "patrol_pattern": validated_patrol_pattern,
                },
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error saving patrol pattern: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to save patrol pattern: {str(e)}",
            }

    @staticmethod
    def preview_patrol_pattern(stream_id: str, patrol_pattern: dict) -> Dict[str, Any]:
        """Preview patrol pattern by simulating camera movements.

        Args:
            stream_id: Stream identifier
            patrol_pattern: Dictionary containing patrol pattern coordinates

        Returns:
            dict: Result with status, message, and preview data
        """
        try:
            # Validate patrol pattern structure
            patrol_pattern_schema = PatrolPatternSchema()

            try:
                validated_patrol_pattern = patrol_pattern_schema.load(patrol_pattern)
            except ValidationError as e:
                return {
                    "status": "error",
                    "message": "Invalid patrol pattern data",
                    "errors": e.messages,
                }

            # Get the coordinates from the validated pattern
            coordinates = validated_patrol_pattern.get("coordinates", [])

            if len(coordinates) < 2:
                return {
                    "status": "error",
                    "message": "Patrol pattern must have at least 2 waypoints",
                }

            # Check if stream is active and has PTZ controller
            video_streaming = streams.get(stream_id)
            if not video_streaming:
                return {
                    "status": "error",
                    "message": "Stream is not currently active. Cannot preview patrol pattern.",
                }

            if not video_streaming.ptz_auto_tracker:
                return {
                    "status": "error",
                    "message": "PTZ controller not available for this stream",
                }

            # Preview the pattern (this would trigger actual camera movement)
            log_event(
                logger,
                "info",
                f"Previewing patrol pattern for stream: {stream_id} with {len(coordinates)} waypoints",
                event_type="info",
            )

            return {
                "status": "success",
                "message": f"Patrol pattern preview initiated with {len(coordinates)} waypoints",
                "data": {
                    "stream_id": stream_id,
                    "waypoint_count": len(coordinates),
                    "coordinates": coordinates,
                },
            }

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error previewing patrol pattern: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to preview patrol pattern: {str(e)}",
            }

    @staticmethod
    def get_patrol_pattern(stream_id: str) -> Dict[str, Any]:
        """Get saved patrol pattern from database.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and patrol pattern data
        """
        try:
            db = get_database()

            # Get stream from database
            stream = db.streams.find_one({"stream_id": stream_id})
            if not stream:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            # Get patrol pattern from stream data
            patrol_pattern = stream.get("patrol_pattern")

            if patrol_pattern is None:
                return {
                    "status": "success",
                    "message": "No patrol pattern configured for this stream",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_pattern": None,
                    },
                }

            log_event(
                logger,
                "info",
                f"Retrieved patrol pattern for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Patrol pattern retrieved successfully",
                "data": {
                    "stream_id": stream_id,
                    "patrol_pattern": patrol_pattern,
                },
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving patrol pattern: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to retrieve patrol pattern: {str(e)}",
            }

    @staticmethod
    def toggle_patrol_focus(stream_id: str) -> Dict[str, Any]:
        """Toggle focus during patrol for a stream.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and new focus state
        """
        try:
            db = get_database()

            # Get stream from database
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            if not stream_doc:
                return {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found.",
                }

            # Toggle enable_focus_during_patrol (default to False if not set)
            current_status = stream_doc.get("enable_focus_during_patrol", False)
            new_status = not current_status

            # Update database
            db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "enable_focus_during_patrol": new_status,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            # Update active stream if it exists
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                video_streaming.ptz_auto_tracker.set_patrol_parameters(
                    enable_focus_during_patrol=new_status
                )
                log_event(
                    logger,
                    "info",
                    f"Updated patrol focus for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Patrol focus toggled to {new_status} for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": f"Patrol focus {'enabled' if new_status else 'disabled'} successfully",
                "data": {
                    "stream_id": stream_id,
                    "enable_focus_during_patrol": new_status,
                },
            }

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error toggling patrol focus: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to toggle patrol focus: {str(e)}",
            }

    @staticmethod
    def toggle_patrol(stream_id: str, mode: str) -> Dict[str, Any]:
        """Toggle patrol mode for a stream.

        Args:
            stream_id: Stream identifier
            mode: Patrol mode ('pattern', 'grid', 'off')

        Returns:
            dict: Result with status, message, and data
        """
        try:
            valid_modes = ["pattern", "grid", "off"]
            if mode not in valid_modes:
                return {
                    "status": "error",
                    "message": f"Invalid mode. Must be one of {valid_modes}",
                }

            db = get_database()
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            if not stream_doc:
                return {
                    "status": "error",
                    "message": "Stream not found",
                    "error_code": "not_found",
                }

            if mode == "pattern":
                patrol_pattern = stream_doc.get("patrol_pattern")
                if (
                    not patrol_pattern
                    or not patrol_pattern.get("coordinates")
                    or len(patrol_pattern.get("coordinates")) < 2
                ):
                    return {
                        "status": "error",
                        "message": "Pattern patrol invalid configuration",
                    }
            elif mode == "grid":
                if not stream_doc.get("patrol_area"):
                    return {
                        "status": "error",
                        "message": "Grid patrol invalid configuration",
                    }

            db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "patrol_enabled": mode != "off",
                        "patrol_mode": mode,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            # Delegate to internal handle_patrol_toggle
            
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            result = PatrolService.handle_patrol_toggle(stream_id, mode, stream_doc)
            
            return {
                "status": "success",
                "message": result.get("message"),
                "data": {
                    "patrol_enabled": result.get("patrol_enabled"),
                    "patrol_mode": result.get("patrol_mode"),
                    "home_position_saved": result.get("home_position_saved", False),
                    "patrol_started": result.get("patrol_started", False),
                    "focus_enabled": result.get("focus_enabled"),
                    "autotrack_enabled": result.get("autotrack_enabled"),
                },
            }

        except Exception as e:
            log_event(
                logger, "error", f"Error toggling patrol: {e}", event_type="error"
            )
            return {
                "status": "error",
                "message": "Failed to toggle patrol",
                "error_code": "toggle_failed",
            }

    @staticmethod
    def change_autotrack(stream_id: str) -> Dict[str, Any]:
        """Toggle PTZ auto tracking for a stream.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and data
        """
        try:
            video_streaming = streams.get(stream_id)
            if video_streaming is None:
                return {
                    "status": "error",
                    "message": "Stream with the give ID is not active!",
                }

            if not video_streaming.ptz_auto_tracker:
                return {
                    "status": "error",
                    "message": "This stream does not support ptz auto tracking!",
                }

            video_streaming.ptz_autotrack = not video_streaming.ptz_autotrack

            from events import emit_event, EventType

            db = get_database()

            if video_streaming.ptz_autotrack:
                if (
                    video_streaming.camera_controller
                    and video_streaming.ptz_auto_tracker
                ):
                    camera_controller = video_streaming.camera_controller
                    pan, tilt, zoom = camera_controller.get_current_position()

                    video_streaming.ptz_auto_tracker.update_default_position(
                        pan, tilt, zoom
                    )

                    stream_doc = db.streams.find_one({"stream_id": stream_id})
                    if stream_doc and stream_doc.get("patrol_enabled", False):
                        enable_focus = stream_doc.get(
                            "enable_focus_during_patrol", False
                        )

                        video_streaming.ptz_auto_tracker.set_patrol_parameters(
                            focus_max_zoom=1.0, enable_focus_during_patrol=enable_focus
                        )

                        patrol_pattern = stream_doc.get("patrol_pattern")
                        if patrol_pattern and patrol_pattern.get("coordinates"):
                            coordinates = patrol_pattern.get("coordinates", [])
                            if len(coordinates) >= 2:
                                video_streaming.ptz_auto_tracker.set_custom_patrol_pattern(
                                    coordinates
                                )
                                video_streaming.ptz_auto_tracker.start_patrol(
                                    mode="pattern"
                                )
                                log_event(
                                    logger,
                                    "info",
                                    f"Started custom pattern patrol for stream {stream_id} with {len(coordinates)} waypoints",
                                    event_type="info",
                                )
                            else:
                                video_streaming.ptz_auto_tracker.set_patrol_parameters(
                                    x_positions=10, y_positions=4
                                )
                                video_streaming.ptz_auto_tracker.start_patrol(
                                    "horizontal", mode="grid"
                                )
                        else:
                            video_streaming.ptz_auto_tracker.set_patrol_parameters(
                                x_positions=10, y_positions=4
                            )
                            video_streaming.ptz_auto_tracker.start_patrol(
                                "horizontal", mode="grid"
                            )
            else:
                if video_streaming.ptz_auto_tracker:
                    video_streaming.ptz_auto_tracker.reset_camera_position()

            room = f"ptz-{stream_id}"
            data = {"ptz_autotrack": video_streaming.ptz_autotrack}
            emit_event(event_type=EventType.PTZ_AUTOTRACK, data=data, room=room)

            return {
                "status": "success",
                "message": "Autotrack changed successfully",
                "data": {"ptz_autotrack": video_streaming.ptz_autotrack},
            }
        except Exception as e:
            log_event(
                logger, "error", f"Error changing autotrack: {e}", event_type="error"
            )
            return {"status": "error", "message": f"Failed to change autotrack: {str(e)}"}

    @staticmethod
    def handle_patrol_toggle(stream_id, mode, stream_doc):
        """Handle patrol toggle operation including stopping, starting, and configuration."""
        db = get_database()
        video_streaming = streams.get(stream_id)
        home_position = None
        can_start_patrol = False
        patrol_result = {"patrol_started": False, "status": "not_attempted"}

        if mode == "off":
            if video_streaming and video_streaming.ptz_auto_tracker:
                if video_streaming.ptz_auto_tracker.is_patrol_active():
                    video_streaming.ptz_auto_tracker.stop_patrol()
                    log_event(
                        logger,
                        "info",
                        f"Stopped patrol for stream {stream_id}",
                        event_type="patrol_stopped",
                    )

                video_streaming.ptz_auto_tracker.reset_camera_position()
                log_event(
                    logger,
                    "info",
                    f"Patrol disabled for stream {stream_id}",
                    event_type="patrol_disabled",
                )

            return {
                "status": "success",
                "message": "Patrol disabled successfully",
                "patrol_enabled": False,
                "patrol_mode": "off",
                "home_position_saved": False,
                "patrol_started": False,
            }

        if video_streaming and video_streaming.ptz_auto_tracker:
            can_start_patrol = True

            if video_streaming.camera_controller:
                try:
                    pan, tilt, zoom = (
                        video_streaming.camera_controller.get_current_position()
                    )
                    home_position = {
                        "pan": pan,
                        "tilt": tilt,
                        "zoom": zoom,
                        "saved_at": datetime.now(timezone.utc),
                    }

                    db.streams.update_one(
                        {"stream_id": stream_id},
                        {"$set": {"patrol_home_position": home_position}},
                    )

                    log_event(
                        logger,
                        "info",
                        f"Saved patrol home position for stream {stream_id}: pan={pan:.3f}, tilt={tilt:.3f}, zoom={zoom:.3f}",
                        event_type="patrol_home_saved",
                    )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to get current camera position: {e}",
                        event_type="warning",
                    )

            if video_streaming.ptz_auto_tracker.is_patrol_active():
                video_streaming.ptz_auto_tracker.stop_patrol()
                log_event(
                    logger,
                    "info",
                    f"Stopped existing patrol for stream {stream_id}",
                    event_type="patrol_stopped",
                )

            if home_position:
                video_streaming.ptz_auto_tracker.update_default_position(
                    home_position["pan"], home_position["tilt"], home_position["zoom"]
                )

            patrol_result = PatrolService.start_patrol_if_enabled(
                stream_id, video_streaming, stream_doc
            )

            if not patrol_result["patrol_started"]:
                log_event(
                    logger,
                    "warning",
                    f"Failed to start patrol for stream {stream_id}: {patrol_result.get('status')}",
                    event_type="patrol_start_failed",
                )

        if can_start_patrol:
            patrol_started = patrol_result.get("patrol_started", False)
            focus_enabled = patrol_result.get("focus_enabled", False)

            if patrol_started:
                message = f"{mode.capitalize()} patrol enabled and started successfully"
            else:
                message = f"{mode.capitalize()} patrol settings saved but failed to start: {patrol_result.get('status')}"

            return {
                "status": "success",
                "message": message,
                "patrol_enabled": True,
                "patrol_mode": mode,
                "home_position_saved": home_position is not None,
                "patrol_started": patrol_started,
                "focus_enabled": focus_enabled,
                "autotrack_enabled": (
                    video_streaming.ptz_autotrack if video_streaming else None
                ),
            }
        else:
            return {
                "status": "success",
                "message": f"{mode.capitalize()} patrol settings saved. Patrol will start when stream is active.",
                "patrol_enabled": True,
                "patrol_mode": mode,
                "home_position_saved": False,
                "patrol_started": False,
            }

    @staticmethod
    def start_patrol_if_enabled(stream_id, video_streaming, stream_doc):
        """Start patrol for a stream if enabled in database."""
        if not stream_doc:
            return {"status": "no_stream_doc", "patrol_started": False}

        if not stream_doc.get("patrol_enabled", False):
            return {"status": "patrol_disabled", "patrol_started": False}

        if not video_streaming or not video_streaming.ptz_auto_tracker:
            return {"status": "no_ptz_tracker", "patrol_started": False}

        patrol_mode = stream_doc.get("patrol_mode", "grid")
        patrol_pattern = stream_doc.get("patrol_pattern")
        enable_focus = stream_doc.get("enable_focus_during_patrol", False)

        video_streaming.ptz_auto_tracker.set_patrol_parameters(
            focus_max_zoom=1.0, enable_focus_during_patrol=enable_focus
        )

        if patrol_mode == "pattern":
            if patrol_pattern and patrol_pattern.get("coordinates"):
                coordinates = patrol_pattern.get("coordinates", [])
                if len(coordinates) >= 2:
                    video_streaming.ptz_auto_tracker.set_custom_patrol_pattern(
                        coordinates
                    )
                    video_streaming.ptz_auto_tracker.start_patrol(mode="pattern")
                    log_event(
                        logger,
                        "info",
                        f"Started pattern patrol for stream {stream_id} with {len(coordinates)} waypoints (enable_focus={enable_focus})",
                        event_type="patrol_started",
                    )
                    return {
                        "status": "success",
                        "patrol_started": True,
                        "patrol_mode": "pattern",
                        "waypoint_count": len(coordinates),
                        "focus_enabled": enable_focus,
                    }
                else:
                    log_event(
                        logger,
                        "warning",
                        f"Pattern patrol enabled but insufficient waypoints for stream {stream_id}",
                        event_type="warning",
                    )
                    return {"status": "insufficient_waypoints", "patrol_started": False}
            else:
                log_event(
                    logger,
                    "warning",
                    f"Pattern patrol enabled but no pattern configured for stream {stream_id}",
                    event_type="warning",
                )
                return {"status": "no_pattern", "patrol_started": False}

        elif patrol_mode == "grid":
            video_streaming.ptz_auto_tracker.set_patrol_parameters(
                x_positions=10,
                y_positions=4,
                focus_max_zoom=1.0,
                enable_focus_during_patrol=enable_focus,
            )
            video_streaming.ptz_auto_tracker.start_patrol("horizontal", mode="grid")
            log_event(
                logger,
                "info",
                f"Started grid patrol for stream {stream_id} (enable_focus={enable_focus})",
                event_type="patrol_started",
            )
            return {
                "status": "success",
                "patrol_started": True,
                "patrol_mode": "grid",
                "focus_enabled": enable_focus,
            }
        else:
            log_event(
                logger,
                "warning",
                f"Invalid patrol mode '{patrol_mode}' for stream {stream_id}",
                event_type="warning",
            )
            return {"status": "invalid_mode", "patrol_started": False}
