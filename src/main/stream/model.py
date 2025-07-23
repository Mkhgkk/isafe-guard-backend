import json
import os
import shutil
from utils.logging_config import get_logger, log_event
import threading
from typing import Optional, Any

from flask import current_app as app  # pyright: ignore[reportMissingImports]
from flask import request  # pyright: ignore[reportMissingImports]
from marshmallow import Schema, ValidationError, fields, validate  # pyright: ignore[reportMissingImports]

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
    ptz_port = fields.Integer()
    ptz_username = fields.String()
    patrol_area = fields.Nested(PatrolAreaSchema, missing=None, allow_none=True)

    # class Meta:
    #     unknown = INCLUDE


stream_schema = StreamSchema()


class Stream:

    def create_stream(self):
        data = json.loads(request.data)
        validation_errors = stream_schema.validate(data)

        # Validate data
        if validation_errors:
            return tools.JsonResp(
                {"message": "Validation failed!", "data": validation_errors}, 400
            )

        # Check if stream id is unique
        stream_id = data["stream_id"]
        existing_stream_id = app.db.streams.find_one({"stream_id": stream_id})
        if existing_stream_id:
            return tools.JsonResp(
                {
                    "message": "There is already a stream with the stream ID.",
                    "error": "stream_id_exists",
                },
                400,
            )

        try:
            data = stream_schema.load(data)
            stream = app.db.streams.insert_one(data)
            inserted_id = str(stream.inserted_id)
            data["_id"] = inserted_id

            return tools.JsonResp(
                {"message": "Stream has been successfully created.", "data": data}, 200
            )
        except Exception as e:
            print(e)
            return tools.JsonResp(
                {
                    "message": "Stream could not be created",
                    "error": "creating_stream_failed",
                },
                400,
            )

    def delete_stream(self):
        # # TODO:
        # # delete all related events

        # # stop stream (if running)
        # # delete the stream
        # pass

        data = json.loads(request.data)
        stream_id = data.get("stream_id")
        stream_dir = os.path.join(STATIC_DIR, stream_id)

        try:
            if os.path.exists(stream_dir):
                shutil.rmtree(
                    stream_dir,
                )
            else:
                print(f"Directory does not exist: {stream_dir}")

            # check if stream is running and stop it
            stream_manager = streams.get(stream_id, None)
            is_stream_running = stream_manager and stream_manager.running

            if is_stream_running:
                Stream.stop_stream(stream_id)

            # delete event videos
            app.db.events.delete_many({"stream_id": stream_id})
            app.db.streams.delete_one({"stream_id": stream_id})

            return tools.JsonResp(
                {"message": "Stream deleted successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            return tools.JsonResp(
                {"message": "Deletion failed!", "error": "stream_deletion_failed"}, 400
            )

    def stop(self):
        data = json.loads(request.data)
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)

        if validation_errors:
            print(validation_errors)
            return tools.JsonResp(
                {"message": "Validation failed!", "error": validation_errors}, 400
            )

        stream_id = data["stream_id"]

        try:
            # Find the stream in the database
            stream = app.db.streams.find_one({"stream_id": stream_id}, {"_id": 0})
            if not stream:
                return tools.JsonResp(
                    {
                        "message": "Stream with the given ID not found.",
                        "error": "stream_not_found",
                    },
                    404,
                )

            # asyncio.run(Stream.start_stream(**stream))
            Stream.stop_stream(stream_id)

            # Update the `is_active` status
            app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": False}}
            )

            return tools.JsonResp(
                {"message": "Stream stopped successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            print(e)
            return tools.JsonResp(
                {"message": "Something went wrong", "error": "internal_error"}, 500
            )

    def restart(self):
        """
        Restart a stream by stopping it and then starting it again.
        Expects JSON data with stream_id.
        """
        try:
            data = json.loads(request.data)
            stream_id_only = StreamSchema(only=("stream_id",))
            validation_errors = stream_id_only.validate(data)
            if validation_errors:
                log_event(logger, "error", f"Validation failed for restart: {validation_errors}", event_type="error")
                return tools.JsonResp(
                    {"message": "Validation failed!", "error": validation_errors}, 400
                )
            
            stream_id = data["stream_id"]
            
            # Check if stream exists in active streams
            video_streaming = streams.get(stream_id)
            # if video_streaming is None:
            #     log_event(logger, "warning", f"Attempted to restart non-existent or inactive stream: {stream_id}", event_type="warning")
            #     return tools.JsonResp(
            #         {
            #             "message": f"Stream with ID '{stream_id}' not found or is not active.",
            #             "error": "stream_not_active",
            #         },
            #         404,
            #     )

            log_event(logger, "info", f"Restarting stream: {stream_id}", event_type="stream_restart")

            # Get stream configuration from database first
            try:
                stream_config = app.db.streams.find_one({"stream_id": stream_id})
                if not stream_config:
                    log_event(logger, "error", f"Stream configuration not found in database: {stream_id}", event_type="error")
                    return tools.JsonResp(
                        {
                            "message": f"Stream configuration not found for '{stream_id}'.",
                            "error": "stream_config_not_found",
                        },
                        404,
                    )
            except Exception as e:
                log_event(logger, "error", f"Database error while fetching stream config {stream_id}: {e}", event_type="error")
                return tools.JsonResp(
                    {"message": "Database error occurred.", "error": "database_error"},
                    500,
                )

            # Stop the stream first if stream is active
            if video_streaming and video_streaming.running:
                try:
                    Stream.stop_stream(stream_id)
                    log_event(logger, "info", f"Successfully stopped stream: {stream_id}", event_type="stream_stop")
                except Exception as e:
                    log_event(logger, "error", f"Error stopping stream {stream_id}: {e}", event_type="error")
                    return tools.JsonResp(
                        {
                            "message": f"Failed to stop stream: {str(e)}",
                            "error": "stop_failed"
                        }, 
                        500
                    )

            # Start the stream with the configuration
            try:
                Stream.start_stream(**stream_config)
                
                # Update the `is_active` status
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": True}}
                )
                
                log_event(logger, "info", f"Successfully restarted stream: {stream_id}", event_type="stream_restart")
                
                return tools.JsonResp(
                    {
                        "message": f"Stream '{stream_id}' restarted successfully.",
                        "data": {"stream_id": stream_id}
                    },
                    200,
                )
                
            except Exception as e:
                log_event(logger, "error", f"Error starting stream {stream_id}: {e}", event_type="error")
                return tools.JsonResp(
                    {
                        "message": f"Failed to start stream after stop: {str(e)}",
                        "error": "start_failed"
                    },
                    500,
                )

        except json.JSONDecodeError:
            log_event(logger, "error", "Failed to decode JSON data in restart request", event_type="error")
            return tools.JsonResp(
                {"message": "Invalid JSON data format.", "error": "invalid_json"}, 
                400
            )
        except Exception as e:
            log_event(logger, "error", f"Unexpected error in restart: {e}", event_type="error")
            return tools.JsonResp(
                {
                    "message": f"An unexpected error occurred: {str(e)}",
                    "error": "internal_error"
                }, 
                500
            )

    def start(self):
        data = json.loads(request.data)
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)

        if validation_errors:
            print(validation_errors)
            return tools.JsonResp(
                {"message": "Validation failed!", "error": validation_errors}, 400
            )

        stream_id = data["stream_id"]

        try:
            # Find the stream in the database
            stream = app.db.streams.find_one({"stream_id": stream_id}, {"_id": 0})
            if not stream:
                return tools.JsonResp(
                    {
                        "message": "Stream with the given ID not found.",
                        "error": "stream_not_found",
                    },
                    404,
                )

            Stream.start_stream(**stream)

            # Update the `is_active` status
            app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": True}}
            )

            return tools.JsonResp(
                {"message": "Stream started successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            print(e)
            return tools.JsonResp(
                {"message": "Something went wrong", "error": "internal_error"}, 500
            )

    def update_stream(self):
        data = json.loads(request.data)
        validation_errors = stream_schema.validate(data)

        if validation_errors:
            return tools.JsonResp(
                {"message": "Validation failed!", "data": validation_errors}, 400
            )

        stream_id = data["stream_id"]
        current_stream = app.db.streams.find_one({"stream_id": stream_id})

        if not current_stream:
            return tools.JsonResp(
                {
                    "message": "Stream with the given ID doesn't exist.",
                    "error": "stream_not_found",
                },
                404,
            )

        # check if stream is running and stop it
        stream_manager = streams.get(stream_id, None)
        is_stream_running = stream_manager and stream_manager.running

        if is_stream_running:
            Stream.stop_stream(stream_id)

        try:
            _stream = stream_schema.load(data)
            _stream = app.db.streams.replace_one({"stream_id": stream_id}, _stream)

            return tools.JsonResp(
                {"message": "Stream has been successfully updated.", "data": data}, 200
            )
        except Exception as e:
            print(e)
            return tools.JsonResp(
                {
                    "message": "Stream could not be updated",
                    "error": "updating_stream_failed",
                },
                400,
            )
        finally:
            if is_stream_running:
                Stream.start_stream(**data)
                # Update the `is_active` status
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": True}}
                )

    def get(self, stream_id):
        resp = tools.JsonResp({"message": "Stream(s) not found!"}, 404)

        if stream_id:
            stream = app.db.streams.find_one({"stream_id": stream_id})
            if stream:
                resp = tools.JsonResp(stream, 200)

        else:
            streams = list(app.db.streams.find())
            if streams:
                resp = tools.JsonResp(streams, 200)

        return resp

    def save_patrol_area(self):
        """Save patrol area to database and update active stream."""
        data = json.loads(request.data)
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
                {"status": "error", "message": "Missing patrol_area in request data"},
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
                    "errors": e.messages
                },
                400,
            )

        # Normalize coordinates according to specific rules
        validated_patrol_area = self._normalize_patrol_coordinates(validated_patrol_area)

        # Check if stream exists in database
        stream = app.db.streams.find_one({"stream_id": stream_id})
        if not stream:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found in database",
                },
                404,
            )

        try:
            # Update patrol area in database
            result = app.db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"patrol_area": validated_patrol_area}}
            )

            if result.modified_count == 0:
                log_event(logger, "warning", f"No document was modified for stream_id: {stream_id}", event_type="warning")

            # Update in-memory stream if it's active
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                video_streaming.ptz_auto_tracker.set_patrol_area(validated_patrol_area)
                log_event(logger, "info", f"Updated patrol area for active stream: {stream_id}", event_type="info")

            log_event(logger, "info", f"Patrol area saved successfully for stream: {stream_id}", event_type="info")
            
            return tools.JsonResp(
                {
                    "status": "success", 
                    "message": "Patrol area saved successfully",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_area": validated_patrol_area
                    }
                }, 
                200
            )
        except Exception as e:
            log_event(logger, "error", f"Error saving patrol area for stream {stream_id}: {e}", event_type="error")
            return tools.JsonResp(
                {"status": "error", "message": f"Failed to save patrol area: {str(e)}"}, 
                500
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
        x_min = patrol_area.get('xMin')
        x_max = patrol_area.get('xMax')
        if x_min is not None and x_max is not None and x_max < x_min:
            normalized_area['xMin'] = x_max
            normalized_area['xMax'] = x_min
            log_event(logger, "info", f"Swapped xMin ({x_min}) and xMax ({x_max}) because xMax was less than xMin", event_type="info")
        
        # Normalize Y coordinates: ensure yMax <= yMin  
        y_min = patrol_area.get('yMin')
        y_max = patrol_area.get('yMax')
        if y_min is not None and y_max is not None and y_max > y_min:
            normalized_area['yMin'] = y_max
            normalized_area['yMax'] = y_min
            log_event(logger, "info", f"Swapped yMin ({y_min}) and yMax ({y_max}) because yMax was greater than yMin", event_type="info")
        
        # zoom_level is handled by schema validation (0.0-1.0 range)
        
        return normalized_area

    def get_patrol_area(self):
        """Get saved patrol area from database."""
        data = json.loads(request.data)
        stream_id = data.get("stream_id")

        # Validate required fields
        if not stream_id:
            return tools.JsonResp(
                {"status": "error", "message": "Missing stream_id in request data"},
                400,
            )

        # Check if stream exists in database
        stream = app.db.streams.find_one({"stream_id": stream_id})
        if not stream:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found in database",
                },
                404,
            )

        try:
            # Get patrol area from stream data
            patrol_area = stream.get("patrol_area")
            
            if patrol_area is None:
                return tools.JsonResp(
                    {
                        "status": "success", 
                        "message": "No patrol area configured for this stream",
                        "data": {
                            "stream_id": stream_id,
                            "patrol_area": None
                        }
                    }, 
                    200
                )

            log_event(logger, "info", f"Retrieved patrol area for stream: {stream_id}", event_type="info")
            
            return tools.JsonResp(
                {
                    "status": "success", 
                    "message": "Patrol area retrieved successfully",
                    "data": {
                        "stream_id": stream_id,
                        "patrol_area": patrol_area
                    }
                }, 
                200
            )
        except Exception as e:
            log_event(logger, "error", f"Error retrieving patrol area for stream {stream_id}: {e}", event_type="error")
            return tools.JsonResp(
                {"status": "error", "message": f"Failed to retrieve patrol area: {str(e)}"}, 
                500
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
        home_pan: Optional[float] = None,
        home_tilt: Optional[float] = None,
        home_zoom: Optional[float] = None,
        patrol_area: Optional[dict] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = all([home_pan, home_tilt, home_zoom])

        if stream_id in streams:
            log_event(logger, "info", f"Stream {stream_id} is already running!", event_type="info")
            return

        # Start the video stream immediately
        video_streaming = StreamManager(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # Schedule stop stream
        # stop_time = datetime.datetime.fromtimestamp(end_timestamp)
        # scheduler.add_job(Stream.stop_stream, 'date', run_date=stop_time, args=[stream_id])
        # print(f"Stream {stream_id} scheduled to stop at {stop_time}.")

        if supports_ptz:
            ptz_thread = threading.Thread(
                target=Stream.initialize_camera_controller, 
                args=(cam_ip, ptz_port, ptz_username, ptz_password, stream_id, patrol_area), 
                daemon=True 
            )
            ptz_thread.start()

    @staticmethod
    def initialize_camera_controller(
        cam_ip, ptz_port, ptz_username, ptz_password, stream_id, patrol_area=None
    ):
        """This function will be executed in a background thread to avoid blocking the loop."""
        try:
            stream = streams[stream_id]
            camera_controller = CameraController(
                cam_ip, ptz_port, ptz_username, ptz_password
            )
            stream.camera_controller = camera_controller

            # if camera controller is initialized successfully, then we initialize auto tracker
            ptz_auto_tracker = PTZAutoTracker(cam_ip, ptz_port, ptz_username, ptz_password)
            stream.ptz_auto_tracker = ptz_auto_tracker

            # Load saved patrol area if available
            if patrol_area:
                try:
                    ptz_auto_tracker.set_patrol_area(patrol_area)
                    log_event(logger, "info", f"Loaded saved patrol area for stream {stream_id}: {patrol_area}", event_type="info")
                except Exception as e:
                    log_event(logger, "warning", f"Failed to set patrol area for stream {stream_id}: {e}", event_type="warning")

            log_event(logger, "info", f"PTZ configured for stream {stream_id}.", event_type="info")
        except Exception as e:
                # Send notification when this fails
                log_event(logger, "info", f"Error initializing PTZ for stream {stream_id}: {e}", event_type="info")


    @staticmethod
    def stop_stream(stream_id):
        if stream_id not in streams:
            # raise ValueError(f"Stream ID {stream_id} does not exist in streams.")
            return

        try:
            video_streaming = streams.get(stream_id)
            if video_streaming:
                video_streaming.stop_streaming()
                video_streaming.camera_controller = None
            else:
                # raise ValueError(f"Stream ID {stream_id} is not active.")
                return

            del streams[stream_id]

            # if stream_id in camera_controllers:
            #     del camera_controllers[stream_id]
        except Exception as e:
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

    @staticmethod
    def start_active_streams():
        streams = list(app.db.streams.find())

        for stream in streams:
            if stream["is_active"]:
                log_event(logger, "info", stream, event_type="info")
                try:
                    Stream.start_stream(**stream)
                except Exception as e:
                    log_event(logger, "error", f"Error starting stream {stream.stream_id}", event_type="error")
