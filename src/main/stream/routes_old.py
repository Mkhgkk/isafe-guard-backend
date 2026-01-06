import os
import cv2
import json
import time
import logging
import traceback
from flask import current_app as app
from flask import Response
from flask import Blueprint
from flask import Flask, request
from urllib.parse import urlparse
from main import tools
from main.shared import safe_area_trackers
from main.shared import streams
from .model import Stream

from events import emit_event, emit_dynamic_event, EventType
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)
stream_blueprint = Blueprint("stream", __name__)

REFERENCE_FRAME_DIR = "../static/frame_refs"
NAMESPACE = "/default"


@stream_blueprint.route("/start_stream", methods=["POST"])
def start_stream():
    """Start a video stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream ID to start
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
      400:
        description: Invalid stream ID or stream already running
    """
    return Stream().start()


@stream_blueprint.route("/stop_stream", methods=["POST"])
def stop_stream():
    """Stop a video stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream ID to stop
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream stopped successfully
      400:
        description: Invalid stream ID
    """
    return Stream().stop()


@stream_blueprint.route("/restart_stream", methods=["POST"])
def restart_stream():
    """Restart a video stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream ID to restart
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream restarted successfully
      400:
        description: Invalid stream ID
    """
    return Stream().restart()


@stream_blueprint.route("/toggle_intrusion_detection", methods=["POST"])
def toggle_intrusion_detection():
    """Toggle intrusion detection for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream ID for toggling intrusion detection
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Intrusion detection toggled successfully
      400:
        description: Invalid stream ID
    """
    return Stream().toggle_intrusion_detection()


@stream_blueprint.route("/toggle_saving_video", methods=["POST"])
def toggle_saving_video():
    """Toggle video recording for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream ID for toggling video saving
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Video saving toggled successfully
      400:
        description: Invalid stream ID
    """
    return Stream().toggle_saving_video()


def stream_video(file_path):
    def generate():
        with open(file_path, "rb") as video_file:
            data = video_file.read(1024 * 1024)  # stream in chunks of 1MB
            while data:
                yield data
                data = video_file.read(1024 * 1024)

    return Response(generate(), mimetype="video/mp4")


@stream_blueprint.route("/change_autotrack", methods=["POST"])
def change_autotrack():
    """Toggle PTZ auto tracking for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID for toggling PTZ auto tracking
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream to toggle auto tracking
    responses:
      200:
        description: Auto tracking toggled successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Autotrack changed successfully
            data:
              type: object
              properties:
                ptz_autotrack:
                  type: boolean
                  description: Current auto tracking state
      400:
        description: Invalid stream ID or stream not active or PTZ not supported
        schema:
          type: object
          properties:
            status:
              type: string
              example: error
            message:
              type: string
    """
    try:
        data = json.loads(request.data)
        stream_id = data["stream_id"]

        video_streaming = streams.get(stream_id)
        if video_streaming is None:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": "Stream with the give ID is not active!",
                },
                400,
            )

        if not video_streaming.ptz_auto_tracker:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": "This stream does not support ptz auto tracking!",
                },
                400,
            )

        video_streaming.ptz_autotrack = not video_streaming.ptz_autotrack

        if video_streaming.ptz_autotrack:
            if video_streaming.camera_controller and video_streaming.ptz_auto_tracker:
                # obtain current ptz coordinates
                camera_controller = video_streaming.camera_controller
                pan, tilt, zoom = camera_controller.get_current_position()

                # set these coordinates and default position
                video_streaming.ptz_auto_tracker.update_default_position(
                    pan, tilt, zoom
                )

                # Check if patrol_enabled is true in database, if true start patrol
                from flask import current_app as app

                stream_doc = app.db.streams.find_one({"stream_id": stream_id})
                if stream_doc and stream_doc.get("patrol_enabled", False):
                    # Get enable_focus_during_patrol setting from database (default: False)
                    enable_focus = stream_doc.get("enable_focus_during_patrol", False)

                    video_streaming.ptz_auto_tracker.set_patrol_parameters(
                        focus_max_zoom=1.0, enable_focus_during_patrol=enable_focus
                    )

                    # Check if there's a custom patrol pattern
                    patrol_pattern = stream_doc.get("patrol_pattern")
                    if patrol_pattern and patrol_pattern.get("coordinates"):
                        # Start pattern patrol
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
                            # Fall back to grid patrol
                            video_streaming.ptz_auto_tracker.set_patrol_parameters(
                                x_positions=10, y_positions=4
                            )
                            video_streaming.ptz_auto_tracker.start_patrol(
                                "horizontal", mode="grid"
                            )
                    else:
                        # No pattern, use grid patrol
                        video_streaming.ptz_auto_tracker.set_patrol_parameters(
                            x_positions=10, y_positions=4
                        )
                        video_streaming.ptz_auto_tracker.start_patrol(
                            "horizontal", mode="grid"
                        )
        else:
            # Stop tracking
            if video_streaming.ptz_auto_tracker:
                video_streaming.ptz_auto_tracker.reset_camera_position()

        # emit change autotrack change
        room = f"ptz-{stream_id}"
        data = {"ptz_autotrack": video_streaming.ptz_autotrack}
        emit_event(event_type=EventType.PTZ_AUTOTRACK, data=data, room=room)

        return tools.JsonResp(
            {
                "status": "Success",
                "message": "Autotrack changed successfully",
                "data": {"ptz_autotrack": video_streaming.ptz_autotrack},
            },
            200,
        )

    except Exception as e:
        print("An error occurred:", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": "wrong data format!"}, 400)


@stream_blueprint.route("/toggle_patrol", methods=["POST"])
def toggle_patrol():
    """Toggle patrol mode for PTZ camera
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - patrol_mode
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            patrol_mode:
              type: string
              enum: [pattern, grid, off]
              example: grid
              description: Patrol mode - 'pattern' for custom waypoints, 'grid' for automatic grid patrol, 'off' to disable
    responses:
      200:
        description: Patrol mode updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or stream not found
      404:
        description: Stream not found
    """
    return Stream().toggle_patrol()


@stream_blueprint.route("/toggle_patrol_focus", methods=["POST"])
def toggle_patrol_focus():
    """Toggle focus during patrol feature
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream configuration for patrol focus
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            enable_focus_during_patrol:
              type: boolean
              example: true
              description: Whether to enable auto-focus during patrol
    responses:
      200:
        description: Patrol focus setting updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().toggle_patrol_focus()


# @stream_blueprint.route("/create_schedule", methods=["POST"])
@stream_blueprint.route("/update_stream", methods=["POST"])
def update_stream():
    """Update stream configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream update data
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream to update
            name:
              type: string
              example: Updated Camera Name
              description: New name for the stream
            location:
              type: string
              example: Building B - Entrance
              description: New location for the stream
            rtsp_url:
              type: string
              example: rtsp://username:password@192.168.1.100:554/stream
              description: Updated RTSP URL
    responses:
      200:
        description: Stream updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().update_stream()


@stream_blueprint.route("/delete_stream", methods=["POST"])
def delete_stream():
    """Delete a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID to delete
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream to delete
    responses:
      200:
        description: Stream deleted successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().delete_stream()


@stream_blueprint.route("/set_danger_zone", methods=["POST"])
def set_danger_zone():
    """Configure safe/danger zone for intrusion detection
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Danger zone configuration
        required: true
        schema:
          type: object
          required:
            - streamId
            - coords
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
            coords:
              type: array
              items:
                type: array
                items:
                  type: number
              example: [[100, 100], [400, 100], [400, 300], [100, 300]]
              description: Array of coordinate pairs defining the danger zone polygon
            image:
              type: string
              example: /static/frame_refs/frame_12345_camera_001.jpg
              description: Path to reference image
            static:
              type: boolean
              example: true
              description: Whether the camera is stationary (true) or can move (false)
    responses:
      200:
        description: Danger zone updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Danger zone updated successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                message:
                  type: string
      400:
        description: Missing required fields or invalid data
      404:
        description: Stream not found
    """
    try:
        data = json.loads(request.data)
        image = data.get("image")
        coords = data.get("coords")
        stream_id = data.get("streamId")
        static_mode = data.get("static", True)  # Default to True (static mode)
        print(data)

        # Save to database first using the Stream model's save method
        stream_model = Stream()

        # Create safe area data structure
        from datetime import datetime, timezone
        from flask import current_app as app

        # Validate required fields
        if not stream_id or not coords:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": "Missing required fields: streamId or coords",
                },
                400,
            )

        # Check if stream exists
        existing_stream = app.db.streams.find_one({"stream_id": stream_id})
        if not existing_stream:
            return tools.JsonResp(
                {"status": "error", "message": "Stream not found"}, 404
            )

        safe_area_data = {
            "coords": coords,
            "static_mode": static_mode,
            "reference_image": image,
            "updated_at": datetime.now(timezone.utc),
        }

        # If no existing safe area, add created_at
        if not existing_stream.get("safe_area"):
            safe_area_data["created_at"] = datetime.now(timezone.utc)

        # Update safe area in database
        result = app.db.streams.update_one(
            {"stream_id": stream_id}, {"$set": {"safe_area": safe_area_data}}
        )

        if result.modified_count == 0:
            logger.warning(f"No document was modified for stream_id: {stream_id}")

        logger.info(f"Safe area saved successfully for stream: {stream_id}")

        parsed_url = urlparse(image)
        path = parsed_url.path
        file_name = os.path.basename(path)

        image_path = os.path.join(
            os.path.dirname(__file__), REFERENCE_FRAME_DIR, file_name
        )
        # reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        reference_frame = cv2.imread(image_path)
        safe_area_box = coords

        # Update in-memory tracker if stream is active
        if stream_id in safe_area_trackers:
            safe_area_tracker = safe_area_trackers[stream_id]
            safe_area_tracker.update_safe_area(reference_frame, safe_area_box)
            safe_area_tracker.set_static_mode(static_mode)

        # Send response
        return tools.JsonResp(
            {
                "status": "Success",
                "message": "Danger zone updated successfully",
                "data": {
                    "static_mode": static_mode,
                    "message": "Camera mode set to {} processing".format(
                        "static" if static_mode else "dynamic"
                    ),
                },
            },
            200,
        )

    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": str(e)}, 400)


@stream_blueprint.route("/set_camera_mode", methods=["POST"])
def set_camera_mode():
    """Set camera mode for hazard area tracking
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Camera mode configuration
        required: true
        schema:
          type: object
          required:
            - streamId
            - static
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
            static:
              type: boolean
              example: true
              description: Camera mode - true for static (stationary), false for dynamic (moving)
    responses:
      200:
        description: Camera mode updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Camera mode updated successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                message:
                  type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    try:
        data = json.loads(request.data)
        stream_id = data.get("streamId")
        static_mode = data.get("static", True)

        # Update database - create minimal safe area entry if none exists
        from flask import current_app as app

        stream_doc = app.db.streams.find_one({"stream_id": stream_id})
        if not stream_doc:
            return tools.JsonResp(
                {"status": "error", "message": "Stream not found"}, 404
            )

        # Update or create safe area with new static mode
        from datetime import datetime, timezone

        if stream_doc.get("safe_area"):
            # Update existing safe area
            result = app.db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "safe_area.static_mode": static_mode,
                        "safe_area.updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            if result.modified_count == 0:
                logger.warning(
                    f"No document was modified when updating static mode for stream_id: {stream_id}"
                )
        else:
            # Create minimal safe area entry
            safe_area_data = {
                "static_mode": static_mode,
                "coords": [],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            result = app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"safe_area": safe_area_data}}
            )
            if result.modified_count == 0:
                logger.warning(
                    f"No document was created when setting static mode for stream_id: {stream_id}"
                )

        logger.info(f"Static mode updated to {static_mode} for stream: {stream_id}")

        # Update in-memory tracker if active
        if stream_id in safe_area_trackers:
            safe_area_tracker = safe_area_trackers[stream_id]
            safe_area_tracker.set_static_mode(static_mode)

        return tools.JsonResp(
            {
                "status": "Success",
                "message": "Camera mode updated successfully",
                "data": {
                    "static_mode": static_mode,
                    "message": "Camera mode set to {} processing".format(
                        "static" if static_mode else "dynamic"
                    ),
                },
            },
            200,
        )

    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": str(e)}, 400)


@stream_blueprint.route("/get_camera_mode", methods=["POST"])
def get_camera_mode():
    """Get current camera mode for hazard area tracking
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - streamId
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Camera mode retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Camera mode retrieved successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                  description: Current camera mode - true for static, false for dynamic
                message:
                  type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    try:
        data = json.loads(request.data)
        stream_id = data.get("streamId")

        # Get from database
        from flask import current_app as app

        stream_doc = app.db.streams.find_one({"stream_id": stream_id})
        if not stream_doc:
            return tools.JsonResp(
                {"status": "error", "message": "Stream not found"}, 404
            )

        # Get static mode from database, default to True
        safe_area = stream_doc.get("safe_area", {})
        static_mode = safe_area.get("static_mode", True)

        return tools.JsonResp(
            {
                "status": "Success",
                "message": "Camera mode retrieved successfully",
                "data": {
                    "static_mode": static_mode,
                    "message": "Camera is in {} mode".format(
                        "static" if static_mode else "dynamic"
                    ),
                },
            },
            200,
        )

    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": str(e)}, 400)


@stream_blueprint.route("/get_safe_area", methods=["POST"])
def get_safe_area():
    """Get saved safe area configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Safe area configuration retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                coords:
                  type: array
                  items:
                    type: array
                    items:
                      type: number
                  description: Coordinate pairs defining the safe area polygon
                static_mode:
                  type: boolean
                  description: Camera mode setting
                reference_image:
                  type: string
                  description: Path to reference image
      400:
        description: Invalid input
      404:
        description: Stream or safe area not found
    """
    return Stream().get_safe_area()


@stream_blueprint.route("/get_current_ptz_values", methods=["POST"])
def get_current_ptz_values():
    """Get current PTZ (Pan-Tilt-Zoom) values
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: PTZ values retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: ok
            data:
              type: object
              properties:
                x:
                  type: number
                  description: Current pan position
                y:
                  type: number
                  description: Current tilt position
                z:
                  type: number
                  description: Current zoom level
      400:
        description: Invalid input or camera controller not available
      404:
        description: Stream not found or not active
      500:
        description: Unexpected error
    """
    try:
        data = json.loads(request.data)
        stream_id = data.get("stream_id")

        if not stream_id:
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": "Missing 'streamId' in request data.",
                },
                400,
            )

        # --- Check if stream exists in the streams dictionary ---
        stream = streams.get(stream_id)
        if stream is None:
            log_event(
                logger,
                "warning",
                f"Attempted to get PTZ for non-existent or inactive stream_id: {stream_id}",
                event_type="warning",
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found or is not active.",
                },
                404,  # Not Found is a suitable status code here
            )
        # --- End Check ---

        camera_controller = stream.camera_controller

        # --- Check specifically if the camera controller exists for this stream ---
        if camera_controller is None:
            log_event(
                logger,
                "warning",
                f"Camera controller is missing for active stream_id: {stream_id}",
                event_type="warning",
            )
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Camera controller not available for stream '{stream_id}'. PTZ control might not be enabled.",
                },
                400,  # Bad Request or perhaps 501 Not Implemented / 503 Service Unavailable
            )
        # --- End Check ---

        current_pan, current_tilt, current_zoom = (
            camera_controller.get_current_position()
        )

        return tools.JsonResp(
            {
                "status": "Success",
                "message": "ok",
                "data": {"x": current_pan, "y": current_tilt, "z": current_zoom},
            },
            200,
        )

    except json.JSONDecodeError:
        log_event(
            logger,
            "error",
            "Failed to decode JSON data in /get_current_ptz_values request.",
            event_type="error",
        )
        return tools.JsonResp(
            {"status": "error", "message": "Invalid JSON data format."}, 400
        )
    except Exception as e:
        # Use app.logger for logging within Flask is standard practice
        log_event(
            logger,
            "error",
            f"An error occurred in /get_current_ptz_values for stream_id '{stream_id if 'stream_id' in locals() else 'unknown'}': {e}",
            event_type="error",
        )
        log_event(
            logger, "error", traceback.format_exc(), event_type="error"
        )  # Log the full traceback
        # --- Convert exception to string for JSON response ---
        error_message = str(e)
        return tools.JsonResp(
            {
                "status": "error",
                "message": f"An unexpected error occurred: {error_message}",
            },
            500,
        )  #


@stream_blueprint.route("/save_patrol_area", methods=["POST"])
def save_patrol_area():
    """Save patrol area configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol area configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - patrol_area
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            patrol_area:
              type: object
              description: Patrol area configuration data
              properties:
                coordinates:
                  type: array
                  items:
                    type: array
                    items:
                      type: number
                  description: Coordinates defining the patrol area
    responses:
      200:
        description: Patrol area saved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().save_patrol_area()


@stream_blueprint.route("/get_patrol_area", methods=["POST"])
def get_patrol_area():
    """Get saved patrol area configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Patrol area retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              description: Patrol area configuration
      400:
        description: Invalid input
      404:
        description: Stream or patrol area not found
    """
    return Stream().get_patrol_area()


@stream_blueprint.route("/save_patrol_pattern", methods=["POST"])
def save_patrol_pattern():
    """Save custom patrol pattern with waypoints
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol pattern configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - coordinates
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            coordinates:
              type: array
              items:
                type: object
                properties:
                  pan:
                    type: number
                    description: Pan position
                  tilt:
                    type: number
                    description: Tilt position
                  zoom:
                    type: number
                    description: Zoom level
              example: [{"pan": 0.1, "tilt": 0.2, "zoom": 1.0}, {"pan": 0.5, "tilt": 0.3, "zoom": 1.5}]
              description: Array of PTZ waypoints for the patrol pattern
    responses:
      200:
        description: Patrol pattern saved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().save_patrol_pattern()


@stream_blueprint.route("/preview_patrol_pattern", methods=["POST"])
def preview_patrol_pattern():
    """Preview custom patrol pattern by executing once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol pattern preview request
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            coordinates:
              type: array
              items:
                type: object
                properties:
                  pan:
                    type: number
                  tilt:
                    type: number
                  zoom:
                    type: number
              description: Optional waypoints to preview. If not provided, uses saved pattern.
    responses:
      200:
        description: Patrol pattern preview started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or no pattern available
      404:
        description: Stream not found or not active
    """
    return Stream().preview_patrol_pattern()


@stream_blueprint.route("/get_patrol_pattern", methods=["POST"])
def get_patrol_pattern():
    """Get saved patrol pattern from database
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Patrol pattern retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                coordinates:
                  type: array
                  items:
                    type: object
                    properties:
                      pan:
                        type: number
                      tilt:
                        type: number
                      zoom:
                        type: number
                  description: Array of PTZ waypoints
      400:
        description: Invalid input
      404:
        description: Stream or patrol pattern not found
    """
    return Stream().get_patrol_pattern()


@stream_blueprint.route("", methods=["POST"])
def create_stream():
    """Create a new stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: stream
        description: Stream configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - rtsp_url
          properties:
            stream_id:
              type: string
              example: camera_001
            rtsp_url:
              type: string
              example: rtsp://username:password@192.168.1.100:554/stream
            name:
              type: string
              example: Front Door Camera
            location:
              type: string
              example: Building A - Entrance
    responses:
      200:
        description: Stream created successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              description: Created stream data
      400:
        description: Invalid input or stream already exists
    """
    return Stream().create_stream()


@stream_blueprint.route("", methods=["GET"])
def get_streams():
    """Get stream(s) information (DEPRECATED - Use /stream/list or /stream/<stream_id> instead)
    ---
    deprecated: true
    tags:
      - Stream
    parameters:
      - in: query
        name: stream_id
        type: string
        required: false
        description: Optional stream ID to get a specific stream. If not provided, returns all streams.
        example: camera_001
    responses:
      200:
        description: |
          DEPRECATED: This endpoint is kept for backward compatibility only.
          - Use GET /stream/list to get all streams (returns array)
          - Use GET /stream/<stream_id> to get a single stream (returns object)

          Returns single stream object if stream_id provided, otherwise returns array of stream objects.
        schema:
          oneOf:
            - type: object
              description: Single stream (when stream_id provided)
              properties:
                _id:
                  type: string
                  description: MongoDB ObjectId
                stream_id:
                  type: string
                  description: Unique stream identifier
                rtsp_link:
                  type: string
                  description: RTSP URL for the camera stream
                model_name:
                  type: string
                  description: AI model name used for detection
                  enum: [PPE, PPEAerial, Ladder, Scaffolding, MobileScaffolding, CuttingWelding, Fire, HeavyEquipment, Proximity, Approtium, NexilisProximity]
                location:
                  type: string
                  description: Physical location of the camera
                description:
                  type: string
                  description: Camera description
                is_active:
                  type: boolean
                  description: Whether the stream is currently running
                ptz_autotrack:
                  type: boolean
                  description: Whether PTZ auto tracking is enabled
                cam_ip:
                  type: string
                  description: Camera IP address (for PTZ control)
                ptz_password:
                  type: string
                  description: PTZ control password
                profile_name:
                  type: string
                  description: ONVIF profile name
                ptz_port:
                  type: integer
                  description: PTZ control port
                ptz_username:
                  type: string
                  description: PTZ control username
                patrol_area:
                  type: object
                  nullable: true
                  description: Grid patrol area configuration
                  properties:
                    xMin:
                      type: number
                    xMax:
                      type: number
                    yMin:
                      type: number
                    yMax:
                      type: number
                    zoom_level:
                      type: number
                patrol_pattern:
                  type: object
                  nullable: true
                  description: Custom patrol pattern with waypoints
                  properties:
                    coordinates:
                      type: array
                      items:
                        type: object
                        properties:
                          x:
                            type: number
                          y:
                            type: number
                          z:
                            type: number
                safe_area:
                  type: object
                  nullable: true
                  description: Hazard/safe area configuration for intrusion detection
                  properties:
                    coords:
                      type: array
                      items:
                        type: array
                        items:
                          type: number
                    static_mode:
                      type: boolean
                    reference_image:
                      type: string
                    created_at:
                      type: string
                      format: date-time
                    updated_at:
                      type: string
                      format: date-time
                intrusion_detection:
                  type: boolean
                  description: Whether intrusion detection is enabled
                saving_video:
                  type: boolean
                  description: Whether video recording is enabled
                patrol_home_position:
                  type: object
                  nullable: true
                  description: Home position for patrol return
                  properties:
                    pan:
                      type: number
                    tilt:
                      type: number
                    zoom:
                      type: number
                    saved_at:
                      type: string
                      format: date-time
                patrol_enabled:
                  type: boolean
                  description: Whether patrol is enabled
                patrol_mode:
                  type: string
                  enum: [pattern, grid, off]
                  description: Current patrol mode
                enable_focus_during_patrol:
                  type: boolean
                  description: Whether auto-focus is enabled during patrol
                unresolved_events:
                  type: integer
                  description: Count of unresolved events for this stream (added by backend)
                has_unresolved:
                  type: boolean
                  description: Whether stream has unresolved events (added by backend)
                focus_enabled:
                  type: boolean
                  description: Whether focus is enabled (derived field)
                is_hazard_area_configured:
                  type: boolean
                  description: Whether hazard area is configured (derived field)
                has_ptz:
                  type: boolean
                  description: Whether stream has PTZ support (derived field)
                is_grid_patrol_configured:
                  type: boolean
                  description: Whether grid patrol is configured (derived field)
                is_pattern_patrol_configured:
                  type: boolean
                  description: Whether pattern patrol is configured (derived field)
            - type: array
              description: Array of streams (when stream_id not provided)
              items:
                type: object
                description: Same structure as single stream object above
      404:
        description: Stream not found
    """

    stream_id = request.args.get("stream_id")
    return Stream().get(stream_id)


@stream_blueprint.route("/list", methods=["GET"])
def get_all_streams():
    """Get all streams
    ---
    tags:
      - Stream
    responses:
      200:
        description: List of all streams retrieved successfully
        schema:
          type: array
          items:
            type: object
            properties:
              _id:
                type: string
                description: MongoDB ObjectId
              stream_id:
                type: string
                description: Unique stream identifier
              rtsp_link:
                type: string
                description: RTSP URL for the camera stream
              model_name:
                type: string
                description: AI model name used for detection
              location:
                type: string
                description: Physical location of the camera
              description:
                type: string
                description: Camera description
              is_active:
                type: boolean
                description: Whether the stream is currently running
              ptz_autotrack:
                type: boolean
                description: Whether PTZ auto tracking is enabled
              unresolved_events:
                type: integer
                description: Count of unresolved events
              has_unresolved:
                type: boolean
                description: Whether stream has unresolved events
              has_ptz:
                type: boolean
                description: Whether stream has PTZ support
    """
    return Stream().get(None)


@stream_blueprint.route("/<stream_id>", methods=["GET"])
def get_stream_by_id(stream_id):
    """Get a single stream by ID
    ---
    tags:
      - Stream
    parameters:
      - in: path
        name: stream_id
        type: string
        required: true
        description: ID of the stream to retrieve
        example: camera_001
    responses:
      200:
        description: Stream retrieved successfully
        schema:
          type: object
          properties:
            _id:
              type: string
              description: MongoDB ObjectId
            stream_id:
              type: string
              description: Unique stream identifier
            rtsp_link:
              type: string
              description: RTSP URL for the camera stream
            model_name:
              type: string
              description: AI model name used for detection
            location:
              type: string
              description: Physical location of the camera
            description:
              type: string
              description: Camera description
            is_active:
              type: boolean
              description: Whether the stream is currently running
            ptz_autotrack:
              type: boolean
              description: Whether PTZ auto tracking is enabled
            cam_ip:
              type: string
              description: Camera IP address (for PTZ control)
            ptz_password:
              type: string
              description: PTZ control password
            profile_name:
              type: string
              description: ONVIF profile name
            ptz_port:
              type: integer
              description: PTZ control port
            ptz_username:
              type: string
              description: PTZ control username
            patrol_area:
              type: object
              nullable: true
              description: Grid patrol area configuration
            patrol_pattern:
              type: object
              nullable: true
              description: Custom patrol pattern with waypoints
            safe_area:
              type: object
              nullable: true
              description: Hazard/safe area configuration
            intrusion_detection:
              type: boolean
              description: Whether intrusion detection is enabled
            saving_video:
              type: boolean
              description: Whether video recording is enabled
            patrol_home_position:
              type: object
              nullable: true
              description: Home position for patrol return
            patrol_enabled:
              type: boolean
              description: Whether patrol is enabled
            patrol_mode:
              type: string
              enum: [pattern, grid, off]
              description: Current patrol mode
            enable_focus_during_patrol:
              type: boolean
              description: Whether auto-focus is enabled during patrol
            unresolved_events:
              type: integer
              description: Count of unresolved events
            has_unresolved:
              type: boolean
              description: Whether stream has unresolved events
            focus_enabled:
              type: boolean
              description: Whether focus is enabled
            is_hazard_area_configured:
              type: boolean
              description: Whether hazard area is configured
            has_ptz:
              type: boolean
              description: Whether stream has PTZ support
            is_grid_patrol_configured:
              type: boolean
              description: Whether grid patrol is configured
            is_pattern_patrol_configured:
              type: boolean
              description: Whether pattern patrol is configured
      404:
        description: Stream not found
    """
    return Stream().get(stream_id)


@stream_blueprint.route("/alert", methods=["GET"])
def alert():
    """Trigger an alert event for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: query
        name: stream_id
        type: string
        required: true
        description: ID of the stream to trigger alert for
        example: camera_001
    responses:
      200:
        description: Alert event triggered successfully
        schema:
          type: object
          properties:
            data:
              type: string
              example: ok
    """

    stream_id = request.args.get("stream_id")

    room = stream_id
    data = {"type": "intrusion"}

    emit_dynamic_event(
        base_event_type=EventType.ALERT, identifier=stream_id, data=data, room=room
    )

    return tools.JsonResp({"data": "ok"}, 200)


@stream_blueprint.route("/bulk_start_streams", methods=["POST"])
def bulk_start_streams():
    """Start multiple streams at once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: List of stream IDs to start
        required: true
        schema:
          type: object
          required:
            - stream_ids
          properties:
            stream_ids:
              type: array
              items:
                type: string
              example: ["camera_001", "camera_002", "camera_003"]
              description: Array of stream IDs to start
    responses:
      200:
        description: Streams started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
            data:
              type: object
              description: Results for each stream
      400:
        description: Missing stream_ids or invalid input
    """
    try:
        data = json.loads(request.data)
        stream_ids = data.get("stream_ids", [])

        if not stream_ids:
            return tools.JsonResp({"message": "stream_ids list is required"}, 400)

        return Stream().bulk_start_streams(stream_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)


@stream_blueprint.route("/bulk_stop_streams", methods=["POST"])
def bulk_stop_streams():
    """Stop multiple streams at once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: List of stream IDs to stop
        required: true
        schema:
          type: object
          required:
            - stream_ids
          properties:
            stream_ids:
              type: array
              items:
                type: string
              example: ["camera_001", "camera_002", "camera_003"]
              description: Array of stream IDs to stop
    responses:
      200:
        description: Streams stopped successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
            data:
              type: object
              description: Results for each stream
      400:
        description: Missing stream_ids or invalid input
    """
    try:
        data = json.loads(request.data)
        stream_ids = data.get("stream_ids", [])

        if not stream_ids:
            return tools.JsonResp({"message": "stream_ids list is required"}, 400)

        return Stream().bulk_stop_streams(stream_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)


@stream_blueprint.route("/get_current_frame", methods=["POST"])
def get_current_frame():
    """Get current frame from an active stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Current frame captured successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: ok
            data:
              type: string
              example: frame_1234567890_camera_001.jpg
              description: Filename of the captured frame
      400:
        description: Invalid input or error capturing frame
      404:
        description: Stream not active
    """

    try:
        # get stream Id
        data = json.loads(request.data)
        stream_id = data.get("stream_id")

        file_name = None

        stream = streams[stream_id]
        if stream is not None:
            frame_buffer = stream.frame_buffer

            while file_name is None:
                # with frame_buffer.mutex:
                if frame_buffer.qsize() > 0:
                    current_frame = frame_buffer.queue[-1]

                    _, buffer = cv2.imencode(
                        ".jpg", current_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    )
                    # current_frame = buffer.tobytes()

                    current_frame_bytes = buffer.tobytes()

                    file_directory = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), REFERENCE_FRAME_DIR)
                    )
                    os.makedirs(file_directory, exist_ok=True)

                    file_name = f"frame_{int(time.time())}_{stream_id}.jpg"
                    file_path = os.path.join(file_directory, file_name)

                    with open(file_path, "wb") as file:
                        file.write(current_frame_bytes)
        else:
            # stream is not active
            return tools.JsonResp(
                {"status": "Error", "message": "Stream inactive!"}, 404
            )

        # Send response
        return tools.JsonResp(
            {"status": "Success", "message": "ok", "data": file_name}, 200
        )

    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": str(e)}, 400)
