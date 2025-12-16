import json
import os
import shutil
from utils.logging_config import get_logger, log_event
import threading
from typing import Optional, Any

from flask import current_app as app  # pyright: ignore[reportMissingImports]
from flask import request  # pyright: ignore[reportMissingImports]
from marshmallow import (
    Schema,
    ValidationError,
    fields,
    validate,
)  # pyright: ignore[reportMissingImports]

from config import STATIC_DIR
from main import tools
from main.shared import streams  # pyright: ignore[reportMissingImports]
from ptz import CameraController, PTZAutoTracker
from streaming import StreamManager

logger = get_logger(__name__)


class PatrolAreaSchema(Schema):
    """Schema for patrol area coordinates."""

    xMin = fields.Float(required=True)
    xMax = fields.Float(required=True)
    yMin = fields.Float(required=True)
    yMax = fields.Float(required=True)
    zoom_level = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class PatrolCoordinateSchema(Schema):
    """Schema for a single patrol coordinate."""

    x = fields.Float(required=True)
    y = fields.Float(required=True)
    z = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class PatrolPatternSchema(Schema):
    """Schema for patrol pattern with multiple coordinates."""

    coordinates = fields.List(
        fields.Nested(PatrolCoordinateSchema),
        required=True,
        validate=validate.Length(min=2),  # At least 2 points for a pattern
    )


class SafeAreaSchema(Schema):
    """Schema for safe/hazard area configuration."""

    coords = fields.List(
        fields.List(fields.Float(), validate=validate.Length(equal=2)),
        required=True,
        validate=validate.Length(min=3),  # At least 3 points for a polygon
    )
    static_mode = fields.Boolean(load_default=True)
    reference_image = fields.String()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class StreamSchema(Schema):
    stream_id = fields.String(required=True)
    rtsp_link = fields.String(required=True)
    model_name = fields.String(
        required=True,
        validate=validate.OneOf(
            [
                "PPE",
                "PPEAerial",
                "Ladder",
                "Scaffolding",
                "MobileScaffolding",
                "CuttingWelding",
                "Fire",
                "HeavyEquipment",
                "Proximity",
                "Approtium",
                "NexilisProximity",
            ]
        ),
    )
    location = fields.String(required=True)
    description = fields.String(required=True)
    is_active = fields.Boolean(load_default=False)
    ptz_autotrack = fields.Boolean(load_default=False)
    supports_ptz = fields.Boolean()
    cam_ip = fields.String()
    ptz_password = fields.String()
    profile_name = fields.String()
    ptz_port = fields.Integer()
    ptz_username = fields.String()
    patrol_area = fields.Nested(PatrolAreaSchema, missing=None, allow_none=True)
    safe_area = fields.Nested(SafeAreaSchema, missing=None, allow_none=True)
    intrusion_detection = fields.Boolean(load_default=False)
    saving_video = fields.Boolean(load_default=True)

    # class Meta:
    #     unknown = INCLUDE


stream_schema = StreamSchema()


class Stream:

    # Helper Methods
    def _parse_request_data(self):
        """Parse and return JSON data from request."""
        try:
            return json.loads(request.data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON data format.")

    def _validate_stream_id_only(self, data):
        """Validate data containing only stream_id field."""
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)
        if validation_errors:
            raise ValueError(f"Validation failed: {validation_errors}")
        return data["stream_id"]

    def _get_stream_from_db(self, stream_id, projection=None):
        """Get stream from database by stream_id."""
        try:
            stream = app.db.streams.find_one({"stream_id": stream_id}, projection)
            if not stream:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")
            return stream
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Database error fetching stream {stream_id}: {e}",
                event_type="error",
            )
            raise ValueError("Database error occurred.")

    def _create_error_response(self, message, error_code=None, status_code=400):
        """Create standardized error response."""
        response_data = {"message": message}
        if error_code:
            response_data["error"] = error_code
        log_event(logger, "error", message, event_type="error")
        return tools.JsonResp(response_data, status_code)

    def _create_success_response(self, message, data=None, status_code=200):
        """Create standardized success response."""
        response_data = {"message": message}
        if data:
            response_data["data"] = data
        return tools.JsonResp(response_data, status_code)

    def create_stream(self):
        try:
            payload = self._parse_request_data()
            data = payload.get("stream")
            start_stream = payload.get("start_stream", False)

            validation_errors = stream_schema.validate(data)

            # Validate data
            if validation_errors:
                return self._create_error_response(
                    "Validation failed!", validation_errors
                )

            # Check if stream id is unique
            stream_id = data["stream_id"]
            existing_stream_id = app.db.streams.find_one({"stream_id": stream_id})
            if existing_stream_id:
                return self._create_error_response(
                    "There is already a stream with the stream ID.", "stream_id_exists"
                )

            # Create the stream
            data = stream_schema.load(data)
            stream = app.db.streams.insert_one(data)
            inserted_id = str(stream.inserted_id)
            data["_id"] = inserted_id

            if start_stream:
                # Start the stream immediately if requested
                Stream.start_stream(**data)
                log_event(
                    logger,
                    "info",
                    f"Stream {stream_id} started immediately after creation.",
                    event_type="stream_start",
                )

            return self._create_success_response(
                "Stream has been successfully created.", data
            )

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(
                logger, "error", f"Error creating stream: {e}", event_type="error"
            )
            return self._create_error_response(
                "Stream could not be created", "creating_stream_failed"
            )

    def delete_stream(self):
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            if not stream_id:
                return self._create_error_response("Missing stream_id in request data")

            stream_dir = os.path.join(STATIC_DIR, stream_id)

            # Remove stream directory if it exists
            if os.path.exists(stream_dir):
                shutil.rmtree(stream_dir)

            # Check if stream is running and stop it
            stream_manager = streams.get(stream_id, None)
            is_stream_running = stream_manager and stream_manager.running

            if is_stream_running:
                Stream.stop_stream(stream_id)

            # Delete event videos and stream from database
            app.db.events.delete_many({"stream_id": stream_id})
            app.db.streams.delete_one({"stream_id": stream_id})

            return self._create_success_response("Stream deleted successfully.", "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(
                logger, "error", f"Error deleting stream: {e}", event_type="error"
            )
            return self._create_error_response(
                "Deletion failed!", "stream_deletion_failed"
            )

    def stop(self):
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)
            stream = self._get_stream_from_db(stream_id, {"_id": 0})

            Stream.stop_stream(stream_id)

            return self._create_success_response("Stream stopped successfully.", "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(
                logger, "error", f"Unexpected error in stop: {e}", event_type="error"
            )
            return self._create_error_response(
                "Something went wrong", "internal_error", 500
            )

    def restart(self):
        """
        Restart a stream by stopping it and then starting it again.
        Expects JSON data with stream_id.
        """
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)

            # Check if stream exists in active streams
            video_streaming = streams.get(stream_id)

            log_event(
                logger,
                "info",
                f"Restarting stream: {stream_id}",
                event_type="stream_restart",
            )

            # Get stream configuration from database
            stream_config = self._get_stream_from_db(stream_id)

            # Stop the stream first if stream is active
            if video_streaming and video_streaming.running:
                try:
                    Stream.stop_stream(stream_id)
                    log_event(
                        logger,
                        "info",
                        f"Successfully stopped stream: {stream_id}",
                        event_type="stream_stop",
                    )
                except Exception as e:
                    log_event(
                        logger,
                        "error",
                        f"Error stopping stream {stream_id}: {e}",
                        event_type="error",
                    )
                    return self._create_error_response(
                        f"Failed to stop stream: {str(e)}", "stop_failed", 500
                    )

            # Start the stream with the configuration
            try:
                Stream.start_stream(**stream_config)

                log_event(
                    logger,
                    "info",
                    f"Successfully restarted stream: {stream_id}",
                    event_type="stream_restart",
                )

                return self._create_success_response(
                    f"Stream '{stream_id}' restarted successfully.",
                    {"stream_id": stream_id},
                )

            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error starting stream {stream_id}: {e}",
                    event_type="error",
                )
                return self._create_error_response(
                    f"Failed to start stream after stop: {str(e)}", "start_failed", 500
                )

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(
                logger, "error", f"Unexpected error in restart: {e}", event_type="error"
            )
            return self._create_error_response(
                f"An unexpected error occurred: {str(e)}", "internal_error", 500
            )

    def start(self):
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)
            stream = self._get_stream_from_db(stream_id, {"_id": 0})

            Stream.start_stream(**stream)

            return self._create_success_response("Stream started successfully.", "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(
                logger, "error", f"Unexpected error in start: {e}", event_type="error"
            )
            return self._create_error_response(
                "Something went wrong", "internal_error", 500
            )

    def update_stream(self):
        try:
            data = self._parse_request_data()
            validation_errors = stream_schema.validate(data)

            if validation_errors:
                return self._create_error_response(
                    "Validation failed!", validation_errors
                )

            stream_id = data["stream_id"]
            current_stream = self._get_stream_from_db(stream_id)

            # Check if stream is running and stop it
            stream_manager = streams.get(stream_id, None)
            is_stream_running = stream_manager and stream_manager.running

            if is_stream_running:
                Stream.stop_stream(stream_id)

            try:
                _stream = stream_schema.load(data)
                app.db.streams.replace_one({"stream_id": stream_id}, _stream)

                return self._create_success_response(
                    "Stream has been successfully updated.", data
                )

            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error updating stream {stream_id}: {e}",
                    event_type="error",
                )
                return self._create_error_response(
                    "Stream could not be updated", "updating_stream_failed"
                )
            finally:
                if is_stream_running:
                    Stream.start_stream(**data)

        except ValueError as e:
            return self._create_error_response(
                str(e), status_code=404 if "not found" in str(e) else 400
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Unexpected error in update_stream: {e}",
                event_type="error",
            )
            return self._create_error_response(
                "Stream could not be updated", "updating_stream_failed"
            )

    def _add_derived_fields(self, stream):
        """Add derived boolean fields to a stream object."""
        # Direct fields from database
        stream["saving_video"] = stream.get("saving_video", True)
        stream["intrusion_detection"] = stream.get("intrusion_detection", False)
        stream["patrol_mode"] = stream.get("patrol_mode", "off")

        # Focus enabled during patrol
        stream["focus_enabled"] = stream.get("enable_focus_during_patrol", False)

        # Hazard area configured (based on safe_area being set)
        stream["is_hazard_area_configured"] = stream.get("safe_area") is not None

        # PTZ support (based on having all required PTZ credentials)
        has_ptz = all([
            stream.get("cam_ip"),
            stream.get("ptz_port"),
            stream.get("ptz_username"),
            stream.get("ptz_password")
        ])
        stream["has_ptz"] = has_ptz

        # Grid patrol configured (based on patrol_area being set)
        stream["is_grid_patrol_configured"] = stream.get("patrol_area") is not None

        # Pattern patrol configured (based on patrol_pattern being set and having coordinates)
        patrol_pattern = stream.get("patrol_pattern")
        stream["is_pattern_patrol_configured"] = (
            patrol_pattern is not None and
            patrol_pattern.get("coordinates") is not None and
            len(patrol_pattern.get("coordinates", [])) >= 2
        )

        return stream

    def get(self, stream_id):
        resp = tools.JsonResp({"message": "Stream(s) not found!"}, 404)

        if stream_id:
            stream = app.db.streams.find_one({"stream_id": stream_id})
            if stream:
                # Add unresolved event count for single stream
                unresolved_count = app.db.events.count_documents(
                    {"stream_id": stream_id, "is_resolved": {"$ne": True}}
                )
                stream["unresolved_events"] = unresolved_count
                stream["has_unresolved"] = unresolved_count > 0

                # Add derived fields
                stream = self._add_derived_fields(stream)

                resp = tools.JsonResp(stream, 200)

        else:
            streams = list(app.db.streams.find())
            if streams:
                # Get unresolved event counts for all streams
                pipeline = [
                    {"$match": {"is_resolved": {"$ne": True}}},
                    {"$group": {"_id": "$stream_id", "unresolved_count": {"$sum": 1}}},
                ]
                event_counts = list(app.db.events.aggregate(pipeline))
                count_dict = {
                    item["_id"]: item["unresolved_count"] for item in event_counts
                }

                # Add event counts and derived fields to each stream
                for stream in streams:
                    unresolved_count = count_dict.get(stream["stream_id"], 0)
                    stream["unresolved_events"] = unresolved_count
                    stream["has_unresolved"] = unresolved_count > 0

                    # Add derived fields
                    stream = self._add_derived_fields(stream)

                resp = tools.JsonResp(streams, 200)

        return resp

    def save_patrol_area(self):
        """Save patrol area to database and update active stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")
            patrol_area = data.get("patrol_area")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing stream_id in request data"},
                    400,
                )

            if not patrol_area:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Missing patrol_area in request data",
                    },
                    400,
                )

            # Validate patrol area structure
            patrol_area_schema = PatrolAreaSchema()

            try:
                validated_patrol_area = patrol_area_schema.load(patrol_area)
            except ValidationError as e:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Invalid patrol area data",
                        "errors": e.messages,
                    },
                    400,
                )

            # Normalize coordinates according to specific rules
            validated_patrol_area = self._normalize_patrol_coordinates(
                validated_patrol_area
            )

            # Check if stream exists in database
            self._get_stream_from_db(stream_id)

            # Update patrol area in database
            result = app.db.streams.update_one(
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

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Patrol area saved successfully",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_area": validated_patrol_area,
                    },
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error saving patrol area: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"status": "error", "message": f"Failed to save patrol area: {str(e)}"},
                500,
            )

    def _normalize_patrol_coordinates(self, patrol_area: dict) -> dict:
        """
        Normalize patrol area coordinates according to specific rules:
        - Ensure xMax is not less than xMin (swap if xMax < xMin)
        - Ensure yMax is not greater than yMin (swap if yMax > yMin)
        - zoom_level is validated by schema and not normalized here

        Args:
            patrol_area: Dictionary containing patrol coordinates and zoom_level

        Returns:
            dict: Normalized patrol area with corrected coordinate values
        """
        normalized_area = patrol_area.copy()

        # Normalize X coordinates: ensure xMax >= xMin
        x_min = patrol_area.get("xMin")
        x_max = patrol_area.get("xMax")
        if x_min is not None and x_max is not None and x_max < x_min:
            normalized_area["xMin"] = x_max
            normalized_area["xMax"] = x_min
            log_event(
                logger,
                "info",
                f"Swapped xMin ({x_min}) and xMax ({x_max}) because xMax was less than xMin",
                event_type="info",
            )

        # Normalize Y coordinates: ensure yMax <= yMin
        y_min = patrol_area.get("yMin")
        y_max = patrol_area.get("yMax")
        if y_min is not None and y_max is not None and y_max > y_min:
            normalized_area["yMin"] = y_max
            normalized_area["yMax"] = y_min
            log_event(
                logger,
                "info",
                f"Swapped yMin ({y_min}) and yMax ({y_max}) because yMax was greater than yMin",
                event_type="info",
            )

        # zoom_level is handled by schema validation (0.0-1.0 range)

        return normalized_area

    def get_patrol_area(self):
        """Get saved patrol area from database."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing stream_id in request data"},
                    400,
                )

            # Get stream from database
            stream = self._get_stream_from_db(stream_id)

            # Get patrol area from stream data
            patrol_area = stream.get("patrol_area")

            if patrol_area is None:
                return tools.JsonResp(
                    {
                        "status": "success",
                        "message": "No patrol area configured for this stream",
                        "data": {"stream_id": stream_id, "patrol_area": None},
                    },
                    200,
                )

            log_event(
                logger,
                "info",
                f"Retrieved patrol area for stream: {stream_id}",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Patrol area retrieved successfully",
                    "data": {"stream_id": stream_id, "patrol_area": patrol_area},
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving patrol area: {e}",
                event_type="error",
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Failed to retrieve patrol area: {str(e)}",
                },
                500,
            )

    def save_patrol_pattern(self):
        """Save patrol pattern to database and update active stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")
            patrol_pattern = data.get("patrol_pattern")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing stream_id in request data"},
                    400,
                )

            if not patrol_pattern:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Missing patrol_pattern in request data",
                    },
                    400,
                )

            # Validate patrol pattern structure
            patrol_pattern_schema = PatrolPatternSchema()

            try:
                validated_patrol_pattern = patrol_pattern_schema.load(patrol_pattern)
            except ValidationError as e:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Invalid patrol pattern data",
                        "errors": e.messages,
                    },
                    400,
                )

            # Check if stream exists in database
            self._get_stream_from_db(stream_id)

            # Update patrol pattern in database
            result = app.db.streams.update_one(
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

            # Update in-memory stream if it's active
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                # Set the custom patrol pattern
                video_streaming.ptz_auto_tracker.set_custom_patrol_pattern(
                    validated_patrol_pattern["coordinates"]
                )
                log_event(
                    logger,
                    "info",
                    f"Updated patrol pattern for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Patrol pattern saved successfully for stream: {stream_id}",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Patrol pattern saved successfully",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_pattern": validated_patrol_pattern,
                    },
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error saving patrol pattern: {e}", event_type="error"
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Failed to save patrol pattern: {str(e)}",
                },
                500,
            )

    def preview_patrol_pattern(self):
        """Preview a patrol pattern by executing it once on the camera."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")
            patrol_pattern = data.get("patrol_pattern")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing stream_id in request data"},
                    400,
                )

            if not patrol_pattern:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Missing patrol_pattern in request data",
                    },
                    400,
                )

            # Validate patrol pattern structure
            patrol_pattern_schema = PatrolPatternSchema()

            try:
                validated_patrol_pattern = patrol_pattern_schema.load(patrol_pattern)
            except ValidationError as e:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Invalid patrol pattern data",
                        "errors": e.messages,
                    },
                    400,
                )

            # Get active stream
            video_streaming = streams.get(stream_id)
            if not video_streaming:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Stream is not active. Please start the stream first.",
                    },
                    400,
                )

            if not video_streaming.ptz_auto_tracker:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "This stream does not support PTZ control.",
                    },
                    400,
                )

            # Preview the patrol pattern (execute once)
            coordinates = validated_patrol_pattern["coordinates"]
            video_streaming.ptz_auto_tracker.preview_custom_patrol_pattern(coordinates, stream_id)

            log_event(
                logger,
                "info",
                f"Previewing patrol pattern for stream: {stream_id} with {len(coordinates)} points",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": f"Patrol pattern preview started with {len(coordinates)} waypoints",
                    "data": {
                        "stream_id": stream_id,
                        "waypoint_count": len(coordinates),
                    },
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error previewing patrol pattern: {e}",
                event_type="error",
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Failed to preview patrol pattern: {str(e)}",
                },
                500,
            )

    def get_patrol_pattern(self):
        """Get saved patrol pattern from database."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing stream_id in request data"},
                    400,
                )

            # Get stream from database
            stream = self._get_stream_from_db(stream_id)

            # Get patrol pattern from stream data
            patrol_pattern = stream.get("patrol_pattern")

            if patrol_pattern is None:
                return tools.JsonResp(
                    {
                        "status": "success",
                        "message": "No patrol pattern configured for this stream",
                        "data": {"stream_id": stream_id, "patrol_pattern": None},
                    },
                    200,
                )

            log_event(
                logger,
                "info",
                f"Retrieved patrol pattern for stream: {stream_id}",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Patrol pattern retrieved successfully",
                    "data": {"stream_id": stream_id, "patrol_pattern": patrol_pattern},
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving patrol pattern: {e}",
                event_type="error",
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Failed to retrieve patrol pattern: {str(e)}",
                },
                500,
            )

    def save_safe_area(self):
        """Save safe area configuration to database and update active stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("streamId")
            coords = data.get("coords")
            static_mode = data.get("static", True)
            reference_image = data.get("image")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing streamId in request data"},
                    400,
                )

            if not coords:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing coords in request data"},
                    400,
                )

            # Create safe area data structure
            from datetime import datetime

            safe_area_data = {
                "coords": coords,
                "static_mode": static_mode,
                "reference_image": reference_image,
                "updated_at": datetime.utcnow(),
            }

            # If no existing safe area, add created_at
            existing_stream = self._get_stream_from_db(stream_id)
            if not existing_stream.get("safe_area"):
                safe_area_data["created_at"] = datetime.utcnow()

            # Validate safe area structure
            safe_area_schema = SafeAreaSchema()

            try:
                validated_safe_area = safe_area_schema.load(safe_area_data)
            except ValidationError as e:
                return tools.JsonResp(
                    {
                        "status": "error",
                        "message": "Invalid safe area data",
                        "errors": e.messages,
                    },
                    400,
                )

            # Update safe area in database
            result = app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"safe_area": validated_safe_area}}
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update the SafeAreaTracker for active stream
            from main.shared import safe_area_trackers

            if stream_id in safe_area_trackers:
                safe_area_tracker = safe_area_trackers[stream_id]
                safe_area_tracker.set_static_mode(static_mode)
                log_event(
                    logger,
                    "info",
                    f"Updated SafeAreaTracker static mode for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Safe area saved successfully for stream: {stream_id}",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Safe area saved successfully",
                    "data": {"stream_id": stream_id, "safe_area": validated_safe_area},
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error saving safe area: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"status": "error", "message": f"Failed to save safe area: {str(e)}"},
                500,
            )

    def get_safe_area(self):
        """Get saved safe area configuration from database."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("streamId")

            # Validate required fields
            if not stream_id:
                return tools.JsonResp(
                    {"status": "error", "message": "Missing streamId in request data"},
                    400,
                )

            # Get stream from database
            stream = self._get_stream_from_db(stream_id)

            # Get safe area from stream data
            safe_area = stream.get("safe_area")

            if safe_area is None:
                return tools.JsonResp(
                    {
                        "status": "success",
                        "message": "No safe area configured for this stream",
                        "data": {
                            "stream_id": stream_id,
                            "safe_area": None,
                            "static_mode": True,  # Default to static
                        },
                    },
                    200,
                )

            log_event(
                logger,
                "info",
                f"Retrieved safe area for stream: {stream_id}",
                event_type="info",
            )

            return tools.JsonResp(
                {
                    "status": "success",
                    "message": "Safe area retrieved successfully",
                    "data": {
                        "stream_id": stream_id,
                        "safe_area": safe_area,
                        "static_mode": safe_area.get("static_mode", True),
                    },
                },
                200,
            )

        except ValueError as e:
            return tools.JsonResp(
                {"status": "error", "message": str(e)},
                404 if "not found" in str(e) else 400,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error retrieving safe area: {e}", event_type="error"
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Failed to retrieve safe area: {str(e)}",
                },
                500,
            )

    @staticmethod
    def start_stream(
        rtsp_link: str,
        model_name: str,
        stream_id: str,
        cam_ip: Optional[str] = None,
        ptz_port: Optional[int] = None,
        ptz_username: Optional[str] = None,
        ptz_password: Optional[str] = None,
        profile_name: Optional[str] = None,
        home_pan: Optional[float] = None,
        home_tilt: Optional[float] = None,
        home_zoom: Optional[float] = None,
        patrol_area: Optional[dict] = None,
        patrol_pattern: Optional[dict] = None,
        safe_area: Optional[dict] = None,
        intrusion_detection: Optional[bool] = None,
        saving_video: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = all([home_pan, home_tilt, home_zoom])

        # Default intrusion detection to False if not specified
        if intrusion_detection is None:
            intrusion_detection = False

        # Default saving video to True if not specified
        if saving_video is None:
            saving_video = True

        if stream_id in streams:
            log_event(
                logger,
                "info",
                f"Stream {stream_id} is already running!",
                event_type="info",
            )
            return

        # Start the video stream immediately
        video_streaming = StreamManager(
            rtsp_link,
            model_name,
            stream_id,
            ptz_autotrack,
            intrusion_detection,
            saving_video,
        )
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # Initialize SafeAreaTracker with saved data if available
        # The SafeAreaTracker is now guaranteed to be in the dictionary since StreamManager is created
        from main.shared import safe_area_trackers

        # Debug logging
        log_event(
            logger,
            "info",
            f"Stream startup debug for {stream_id}: safe_area={'exists' if safe_area else 'None'}, tracker_in_dict={stream_id in safe_area_trackers}",
            event_type="info",
        )
        if safe_area:
            log_event(
                logger,
                "info",
                f"Safe area data: static_mode={safe_area.get('static_mode', 'missing')}, coords_count={len(safe_area.get('coords', []))}, ref_image={safe_area.get('reference_image', 'missing')}",
                event_type="info",
            )

        if safe_area and stream_id in safe_area_trackers:
            safe_area_tracker = safe_area_trackers[stream_id]
            try:
                # Set static mode from database
                static_mode = safe_area.get("static_mode", True)
                safe_area_tracker.set_static_mode(static_mode)

                # Load safe area coordinates if they exist
                coords = safe_area.get("coords")
                reference_image = safe_area.get("reference_image")

                if coords and len(coords) > 0:
                    # Try to load reference frame and set up safe area
                    if reference_image:
                        try:
                            import cv2
                            import os
                            from urllib.parse import urlparse

                            # Parse the reference image path using same logic as routes.py
                            parsed_url = urlparse(reference_image)
                            file_name = os.path.basename(parsed_url.path)

                            # Use same path construction as in routes.py
                            REFERENCE_FRAME_DIR = "../static/frame_refs"
                            image_path = os.path.join(
                                os.path.dirname(__file__),
                                REFERENCE_FRAME_DIR,
                                file_name,
                            )

                            log_event(
                                logger,
                                "info",
                                f"Attempting to load reference image for {stream_id}: {image_path} (from {reference_image})",
                                event_type="info",
                            )

                            # Load the reference frame
                            reference_frame = cv2.imread(image_path)
                            if reference_frame is not None:
                                safe_area_tracker.update_safe_area(
                                    reference_frame, coords
                                )
                                log_event(
                                    logger,
                                    "info",
                                    f"Loaded safe area with {len(coords)} zones and reference frame for stream {stream_id}",
                                    event_type="info",
                                )
                            else:
                                log_event(
                                    logger,
                                    "warning",
                                    f"Could not load reference frame for stream {stream_id}: {image_path}",
                                    event_type="warning",
                                )
                        except Exception as img_e:
                            log_event(
                                logger,
                                "warning",
                                f"Failed to load reference frame for stream {stream_id}: {img_e}",
                                event_type="warning",
                            )

                    log_event(
                        logger,
                        "info",
                        f"Loaded safe area static mode ({static_mode}) with {len(coords)} coordinate zones for stream {stream_id}",
                        event_type="info",
                    )
                else:
                    log_event(
                        logger,
                        "info",
                        f"Loaded safe area static mode ({static_mode}) for stream {stream_id} (no coordinates)",
                        event_type="info",
                    )

            except Exception as e:
                log_event(
                    logger,
                    "warning",
                    f"Failed to initialize safe area for stream {stream_id}: {e}",
                    event_type="warning",
                )
        elif safe_area:
            log_event(
                logger,
                "warning",
                f"Safe area data exists for stream {stream_id} but SafeAreaTracker not found in registry",
                event_type="warning",
            )
        elif stream_id in safe_area_trackers:
            log_event(
                logger,
                "info",
                f"SafeAreaTracker exists for stream {stream_id} but no safe area data in database",
                event_type="info",
            )
        else:
            log_event(
                logger,
                "info",
                f"No safe area configuration found for stream {stream_id} and no tracker registered",
                event_type="info",
            )

        # Update the database to mark stream as active
        try:
            app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": True}}
            )
            log_event(
                logger,
                "info",
                f"Updated stream {stream_id} status to active in database",
                event_type="info",
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Failed to update stream {stream_id} active status in database: {e}",
                event_type="error",
            )

        # Schedule stop stream
        # stop_time = datetime.datetime.fromtimestamp(end_timestamp)
        # scheduler.add_job(Stream.stop_stream, 'date', run_date=stop_time, args=[stream_id])
        # print(f"Stream {stream_id} scheduled to stop at {stop_time}.")

        if supports_ptz:
            ptz_thread = threading.Thread(
                target=Stream.initialize_camera_controller,
                args=(
                    cam_ip,
                    ptz_port,
                    ptz_username,
                    ptz_password,
                    stream_id,
                    profile_name,
                    patrol_area,
                    patrol_pattern,
                ),
                daemon=True,
            )
            ptz_thread.start()

    @staticmethod
    def handle_patrol_toggle(stream_id, mode, stream_doc):
        """Handle patrol toggle operation including stopping, starting, and configuration.

        Args:
            stream_id: Stream identifier
            mode: Patrol mode ('pattern', 'grid', or 'off')
            stream_doc: Stream document from database

        Returns:
            dict: Result with status, messages, and patrol information
        """
        from main.shared import streams
        from datetime import datetime, timezone
        from flask import current_app as app

        video_streaming = streams.get(stream_id)
        home_position = None
        can_start_patrol = False
        patrol_result = {"patrol_started": False, "status": "not_attempted"}

        # Handle turning off patrol
        if mode == "off":
            if video_streaming and video_streaming.ptz_auto_tracker:
                # Stop any currently running patrol
                if video_streaming.ptz_auto_tracker.is_patrol_active():
                    video_streaming.ptz_auto_tracker.stop_patrol()
                    log_event(
                        logger,
                        "info",
                        f"Stopped patrol for stream {stream_id}",
                        event_type="patrol_stopped",
                    )

                # Reset camera to home position
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

        # Handle enabling patrol (pattern or grid)
        if video_streaming and video_streaming.ptz_auto_tracker:
            can_start_patrol = True

            # Save current camera position as home
            if video_streaming.camera_controller:
                try:
                    pan, tilt, zoom = video_streaming.camera_controller.get_current_position()
                    home_position = {
                        "pan": pan,
                        "tilt": tilt,
                        "zoom": zoom,
                        "saved_at": datetime.now(timezone.utc),
                    }

                    # Update database with home position
                    app.db.streams.update_one(
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

            # Stop any currently running patrol first
            if video_streaming.ptz_auto_tracker.is_patrol_active():
                video_streaming.ptz_auto_tracker.stop_patrol()
                log_event(
                    logger,
                    "info",
                    f"Stopped existing patrol for stream {stream_id}",
                    event_type="patrol_stopped",
                )

            # Update home position in tracker if we captured it
            if home_position:
                video_streaming.ptz_auto_tracker.update_default_position(
                    home_position["pan"], home_position["tilt"], home_position["zoom"]
                )

            # Start patrol using centralized method
            patrol_result = Stream.start_patrol_if_enabled(stream_id, video_streaming, stream_doc)

            if not patrol_result["patrol_started"]:
                log_event(
                    logger,
                    "warning",
                    f"Failed to start patrol for stream {stream_id}: {patrol_result.get('status')}",
                    event_type="patrol_start_failed",
                )

        # Prepare response
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
                "autotrack_enabled": video_streaming.ptz_autotrack if video_streaming else None,
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
        """Start patrol for a stream if enabled in database.

        Args:
            stream_id: Stream identifier
            video_streaming: Active StreamManager instance
            stream_doc: Stream document from database

        Returns:
            dict: Result with status, patrol_started, and patrol_mode
        """
        if not stream_doc:
            return {"status": "no_stream_doc", "patrol_started": False}

        if not stream_doc.get("patrol_enabled", False):
            return {"status": "patrol_disabled", "patrol_started": False}

        if not video_streaming or not video_streaming.ptz_auto_tracker:
            return {"status": "no_ptz_tracker", "patrol_started": False}

        patrol_mode = stream_doc.get("patrol_mode", "grid")
        patrol_pattern = stream_doc.get("patrol_pattern")
        enable_focus = stream_doc.get("enable_focus_during_patrol", False)

        # Configure patrol parameters
        video_streaming.ptz_auto_tracker.set_patrol_parameters(
            focus_max_zoom=1.0,
            enable_focus_during_patrol=enable_focus
        )

        # Start patrol based on mode
        if patrol_mode == "pattern":
            if patrol_pattern and patrol_pattern.get("coordinates"):
                coordinates = patrol_pattern.get("coordinates", [])
                if len(coordinates) >= 2:
                    video_streaming.ptz_auto_tracker.set_custom_patrol_pattern(coordinates)
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
                        "focus_enabled": enable_focus
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
            video_streaming.ptz_auto_tracker.set_patrol_parameters(x_positions=10, y_positions=4)
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
                "focus_enabled": enable_focus
            }
        else:
            log_event(
                logger,
                "warning",
                f"Invalid patrol mode '{patrol_mode}' for stream {stream_id}",
                event_type="warning",
            )
            return {"status": "invalid_mode", "patrol_started": False}

    @staticmethod
    def initialize_camera_controller(
        cam_ip,
        ptz_port,
        ptz_username,
        ptz_password,
        stream_id,
        profile_name=None,
        patrol_area=None,
        patrol_pattern=None,
    ):
        """This function will be executed in a background thread to avoid blocking the loop."""
        try:
            stream = streams[stream_id]
            camera_controller = CameraController(
                cam_ip, ptz_port, ptz_username, ptz_password, profile_name
            )
            stream.camera_controller = camera_controller

            # if camera controller is initialized successfully, then we initialize auto tracker
            ptz_auto_tracker = PTZAutoTracker(
                cam_ip, ptz_port, ptz_username, ptz_password, profile_name
            )
            stream.ptz_auto_tracker = ptz_auto_tracker

            # Load saved patrol area if available
            if patrol_area:
                try:
                    ptz_auto_tracker.set_patrol_area(patrol_area)
                    log_event(
                        logger,
                        "info",
                        f"Loaded saved patrol area for stream {stream_id}: {patrol_area}",
                        event_type="info",
                    )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to set patrol area for stream {stream_id}: {e}",
                        event_type="warning",
                    )

            # Load saved patrol pattern if available
            if patrol_pattern and patrol_pattern.get("coordinates"):
                try:
                    coordinates = patrol_pattern.get("coordinates", [])
                    if len(coordinates) >= 2:
                        ptz_auto_tracker.set_custom_patrol_pattern(coordinates)
                        log_event(
                            logger,
                            "info",
                            f"Loaded saved patrol pattern for stream {stream_id} with {len(coordinates)} waypoints",
                            event_type="info",
                        )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to set patrol pattern for stream {stream_id}: {e}",
                        event_type="warning",
                    )

            log_event(
                logger,
                "info",
                f"PTZ configured for stream {stream_id}.",
                event_type="info",
            )

            # Auto-start patrol if enabled in database
            from database import get_database
            db = get_database()
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            result = Stream.start_patrol_if_enabled(stream_id, stream, stream_doc)
            if result["patrol_started"]:
                log_event(
                    logger,
                    "info",
                    f"Auto-started {result['patrol_mode']} patrol on system restart for stream {stream_id}",
                    event_type="patrol_auto_started",
                )

        except Exception as e:
            # Send notification when this fails
            log_event(
                logger,
                "error",
                f"Error initializing PTZ for stream {stream_id}: {e}",
                event_type="error",
            )

    @staticmethod
    def stop_stream(stream_id):
        if stream_id not in streams:
            # Stream not in memory, but still update database status if needed
            try:
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
                log_event(
                    logger,
                    "info",
                    f"Updated stream {stream_id} status to inactive in database (not in memory)",
                    event_type="info",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Failed to update stream {stream_id} inactive status in database: {e}",
                    event_type="error",
                )
            return

        try:
            video_streaming = streams.get(stream_id)
            if video_streaming:
                video_streaming.stop_streaming()
                video_streaming.camera_controller = None
            else:
                return

            del streams[stream_id]

            # Update the database to mark stream as inactive
            try:
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
                log_event(
                    logger,
                    "info",
                    f"Updated stream {stream_id} status to inactive in database",
                    event_type="info",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Failed to update stream {stream_id} inactive status in database: {e}",
                    event_type="error",
                )

            # if stream_id in camera_controllers:
            #     del camera_controllers[stream_id]
        except Exception as e:
            # Still try to update database even if stopping failed
            try:
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
            except Exception:
                pass
            raise RuntimeError(f"Failed to stop stream {stream_id}: {e}")

    @staticmethod
    def update_rtsp_link(stream_id, rtsp_link):
        stream = streams.get(stream_id)
        if stream is None:
            raise ValueError(f"Stream ID {stream_id} does not exist.")

        if not rtsp_link:
            raise ValueError("Invalid RTSP link provided.")

        try:
            if stream.running:
                stream.stop_streaming()
                stream.rtsp_link = rtsp_link
                # stream.start_stream()
            else:
                stream.rtsp_link = rtsp_link

        except Exception as e:
            raise RuntimeError(
                f"Failed to update RTSP link for stream {stream_id}: {e}"
            )

    def toggle_intrusion_detection(self):
        """Toggle intrusion detection for a stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            if not stream_id:
                return self._create_error_response("Missing stream_id in request data")

            # Get current stream from database
            current_stream = self._get_stream_from_db(stream_id)

            # Check if safe area is configured when trying to enable intrusion detection
            current_intrusion = current_stream.get("intrusion_detection", False)
            new_intrusion_value = not current_intrusion

            # If trying to enable intrusion detection, check if safe area is configured
            if new_intrusion_value and not current_stream.get("safe_area"):
                return self._create_error_response(
                    "Please configure a hazard area before enabling intrusion detection",
                    "hazard_area_required",
                )

            # Update in database
            result = app.db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"intrusion_detection": new_intrusion_value}},
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update running stream if it exists
            stream_manager = streams.get(stream_id)
            if stream_manager and stream_manager.running:
                stream_manager.set_intrusion_detection(new_intrusion_value)
                log_event(
                    logger,
                    "info",
                    f"Updated running stream intrusion detection for {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Intrusion detection toggled for stream {stream_id}: {current_intrusion} -> {new_intrusion_value}",
                event_type="info",
            )

            return self._create_success_response(
                f"Intrusion detection {'enabled' if new_intrusion_value else 'disabled'} for stream {stream_id}",
                {"stream_id": stream_id, "intrusion_detection": new_intrusion_value},
            )

        except ValueError as e:
            return self._create_error_response(
                str(e), status_code=404 if "not found" in str(e) else 400
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error toggling intrusion detection: {e}",
                event_type="error",
            )
            return self._create_error_response(
                "Failed to toggle intrusion detection", "toggle_intrusion_failed"
            )

    def toggle_patrol(self):
        """Toggle patrol mode for a stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")
            mode = data.get("mode")  # 'pattern', 'grid', or 'off'

            if not stream_id:
                return self._create_error_response("Missing 'stream_id' in request data.")

            if not mode:
                return self._create_error_response(
                    "Missing 'mode' in request data. Must be 'pattern', 'grid', or 'off'."
                )

            # Validate mode
            valid_modes = ["pattern", "grid", "off"]
            if mode not in valid_modes:
                return self._create_error_response(
                    f"Invalid mode '{mode}'. Must be one of: {', '.join(valid_modes)}"
                )

            from datetime import datetime, timezone

            # Get stream from database
            stream_doc = self._get_stream_from_db(stream_id)

            # Validate required configuration for each mode
            if mode == "pattern":
                patrol_pattern = stream_doc.get("patrol_pattern")
                if not patrol_pattern or not patrol_pattern.get("coordinates"):
                    return self._create_error_response(
                        "Cannot enable pattern patrol: no patrol pattern configured. Please save a patrol pattern first."
                    )
                if len(patrol_pattern.get("coordinates", [])) < 2:
                    return self._create_error_response(
                        "Cannot enable pattern patrol: patrol pattern must have at least 2 waypoints."
                    )
            elif mode == "grid":
                patrol_area = stream_doc.get("patrol_area")
                if not patrol_area:
                    return self._create_error_response(
                        "Cannot enable grid patrol: no patrol area configured. Please save a patrol area first."
                    )

            # Update database
            app.db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "patrol_enabled": mode != "off",
                        "patrol_mode": mode,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            # Refresh stream_doc after database update
            stream_doc = self._get_stream_from_db(stream_id)

            # Handle patrol toggle using static method
            result = Stream.handle_patrol_toggle(stream_id, mode, stream_doc)

            return tools.JsonResp(
                {
                    "status": "Success",
                    "message": result.get("message", "Patrol operation completed"),
                    "data": {
                        "patrol_enabled": result.get("patrol_enabled"),
                        "patrol_mode": result.get("patrol_mode"),
                        "home_position_saved": result.get("home_position_saved", False),
                        "patrol_started": result.get("patrol_started", False),
                        "focus_enabled": result.get("focus_enabled"),
                        "autotrack_enabled": result.get("autotrack_enabled"),
                    },
                },
                200,
            )

        except ValueError as e:
            return self._create_error_response(
                str(e), status_code=404 if "not found" in str(e) else 400
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error toggling patrol: {e}", event_type="error"
            )
            return self._create_error_response(
                "Failed to toggle patrol", "toggle_patrol_failed", 500
            )

    def toggle_patrol_focus(self):
        """Toggle enable_focus_during_patrol status in database."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            if not stream_id:
                return self._create_error_response("Missing 'stream_id' in request data.")

            from datetime import datetime, timezone
            from main.shared import streams

            # Get current status from database
            stream_doc = self._get_stream_from_db(stream_id)

            # Toggle enable_focus_during_patrol (default to False if not set)
            current_status = stream_doc.get("enable_focus_during_patrol", False)
            new_status = not current_status

            # Update database
            app.db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "enable_focus_during_patrol": new_status,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            # If stream is active and has ptz_auto_tracker, update the setting immediately
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                video_streaming.ptz_auto_tracker.set_patrol_parameters(
                    enable_focus_during_patrol=new_status
                )
                log_event(
                    logger,
                    "info",
                    f"Updated patrol focus setting for active stream {stream_id}: {new_status}",
                    event_type="patrol_focus_updated",
                )

            return self._create_success_response(
                f"Patrol focus {'enabled' if new_status else 'disabled'} successfully",
                {"enable_focus_during_patrol": new_status},
            )

        except ValueError as e:
            return self._create_error_response(
                str(e), status_code=404 if "not found" in str(e) else 400
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error toggling patrol focus: {e}", event_type="error"
            )
            return self._create_error_response(
                "Failed to toggle patrol focus", "toggle_patrol_focus_failed", 500
            )

    def toggle_saving_video(self):
        """Toggle saving video for a stream."""
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            if not stream_id:
                return self._create_error_response("Missing stream_id in request data")

            # Get current stream from database
            current_stream = self._get_stream_from_db(stream_id)

            # Toggle saving video state
            current_saving_video = current_stream.get("saving_video", True)
            new_saving_video_value = not current_saving_video

            # Update in database
            result = app.db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"saving_video": new_saving_video_value}},
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update running stream if it exists
            stream_manager = streams.get(stream_id)
            if stream_manager and stream_manager.running:
                stream_manager.set_saving_video(new_saving_video_value)
                log_event(
                    logger,
                    "info",
                    f"Updated running stream saving video for {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Saving video toggled for stream {stream_id}: {current_saving_video} -> {new_saving_video_value}",
                event_type="info",
            )

            return self._create_success_response(
                f"Saving video {'enabled' if new_saving_video_value else 'disabled'} for stream {stream_id}",
                {"stream_id": stream_id, "saving_video": new_saving_video_value},
            )

        except ValueError as e:
            return self._create_error_response(
                str(e), status_code=404 if "not found" in str(e) else 400
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error toggling saving video: {e}", event_type="error"
            )
            return self._create_error_response(
                "Failed to toggle saving video", "toggle_saving_video_failed"
            )

    def bulk_start_streams(self, stream_ids):
        """Start multiple streams by their IDs."""
        try:
            results = []
            failed_streams = []

            for stream_id in stream_ids:
                try:
                    # Get stream from database
                    stream_doc = app.db.streams.find_one({"stream_id": stream_id})
                    if not stream_doc:
                        failed_streams.append(
                            {"stream_id": stream_id, "error": "Stream not found"}
                        )
                        continue

                    # Start the stream
                    Stream.start_stream(**stream_doc)
                    results.append({"stream_id": stream_id, "status": "started"})

                except Exception as e:
                    failed_streams.append({"stream_id": stream_id, "error": str(e)})

            response_data = {
                "started_streams": results,
                "failed_streams": failed_streams,
                "total_requested": len(stream_ids),
                "successful_starts": len(results),
            }

            if failed_streams:
                return tools.JsonResp(
                    {
                        "message": f"Bulk start completed with {len(failed_streams)} failures",
                        "data": response_data,
                    },
                    207,
                )  # Multi-status
            else:
                return tools.JsonResp(
                    {
                        "message": "All streams started successfully",
                        "data": response_data,
                    },
                    200,
                )

        except Exception as e:
            log_event(
                logger, "error", f"Error in bulk start streams: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"message": "Failed to start streams", "error": str(e)}, 500
            )

    def bulk_stop_streams(self, stream_ids):
        """Stop multiple streams by their IDs."""
        try:
            results = []
            failed_streams = []

            for stream_id in stream_ids:
                try:
                    # Check if stream exists
                    stream_doc = app.db.streams.find_one({"stream_id": stream_id})
                    if not stream_doc:
                        failed_streams.append(
                            {"stream_id": stream_id, "error": "Stream not found"}
                        )
                        continue

                    # Stop the stream
                    Stream.stop_stream(stream_id)
                    results.append({"stream_id": stream_id, "status": "stopped"})

                except Exception as e:
                    failed_streams.append({"stream_id": stream_id, "error": str(e)})

            response_data = {
                "stopped_streams": results,
                "failed_streams": failed_streams,
                "total_requested": len(stream_ids),
                "successful_stops": len(results),
            }

            if failed_streams:
                return tools.JsonResp(
                    {
                        "message": f"Bulk stop completed with {len(failed_streams)} failures",
                        "data": response_data,
                    },
                    207,
                )  # Multi-status
            else:
                return tools.JsonResp(
                    {
                        "message": "All streams stopped successfully",
                        "data": response_data,
                    },
                    200,
                )

        except Exception as e:
            log_event(
                logger, "error", f"Error in bulk stop streams: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"message": "Failed to stop streams", "error": str(e)}, 500
            )

    @staticmethod
    def start_active_streams():
        streams = list(app.db.streams.find())

        for stream in streams:
            if stream["is_active"]:
                log_event(logger, "info", stream, event_type="info")
                try:
                    Stream.start_stream(**stream)
                except Exception as e:
                    log_event(
                        logger,
                        "error",
                        f"Error starting stream {stream.stream_id}",
                        event_type="error",
                    )
