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
    return Stream().start()


@stream_blueprint.route("/stop_stream", methods=["POST"])
def stop_stream():
    return Stream().stop()


@stream_blueprint.route("/restart_stream", methods=["POST"])
def restart_stream():
    return Stream().restart()


@stream_blueprint.route("/toggle_intrusion_detection", methods=["POST"])
def toggle_intrusion_detection():
    return Stream().toggle_intrusion_detection()


@stream_blueprint.route("/toggle_saving_video", methods=["POST"])
def toggle_saving_video():
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
                    video_streaming.ptz_auto_tracker.set_patrol_parameters(
                        focus_max_zoom=1.0
                    )
                    video_streaming.ptz_auto_tracker.set_patrol_parameters(
                        x_positions=10, y_positions=4, dwell_time=1.5
                    )
                    video_streaming.ptz_auto_tracker.start_patrol("horizontal")
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
    """Toggle patrol_enabled status in database."""
    try:
        data = json.loads(request.data)
        stream_id = data.get("stream_id")

        if not stream_id:
            return tools.JsonResp(
                {"status": "error", "message": "Missing 'stream_id' in request data."},
                400,
            )

        from datetime import datetime, timezone
        from flask import current_app as app

        # Get current status from database
        stream_doc = app.db.streams.find_one({"stream_id": stream_id})
        if not stream_doc:
            return tools.JsonResp(
                {"status": "error", "message": "Stream not found"}, 404
            )

        # Toggle patrol_enabled
        current_status = stream_doc.get("patrol_enabled", False)
        new_status = not current_status

        # Update database
        app.db.streams.update_one(
            {"stream_id": stream_id},
            {
                "$set": {
                    "patrol_enabled": new_status,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        # If toggling off, stop patrol if stream is active and patrol is running
        if not new_status:
            video_streaming = streams.get(stream_id)
            if video_streaming and video_streaming.ptz_auto_tracker:
                if video_streaming.ptz_auto_tracker.is_patrol_active():
                    video_streaming.ptz_auto_tracker.stop_patrol()
                    video_streaming.ptz_auto_tracker.reset_camera_position()

        return tools.JsonResp(
            {
                "status": "Success",
                "message": f"Patrol {'enabled' if new_status else 'disabled'} successfully",
                "data": {"patrol_enabled": new_status},
            },
            200,
        )

    except Exception as e:
        logger.error(f"Error in toggle_patrol: {e}")
        traceback.print_exc()
        return tools.JsonResp(
            {"status": "error", "message": str(e)},
            500,
        )


# @stream_blueprint.route("/create_schedule", methods=["POST"])
@stream_blueprint.route("/update_stream", methods=["POST"])
def update_stream():
    return Stream().update_stream()


@stream_blueprint.route("/delete_stream", methods=["POST"])
def delete_stream():
    return Stream().delete_stream()


@stream_blueprint.route("/set_danger_zone", methods=["POST"])
def set_danger_zone():
    """
    get image data
    get list of of coordinates
    get current ptz location (consider that the camera can be moved)
    get static mode preference (whether camera is moving or stationary)
    Save to database and update in-memory tracker
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
    """
    Update the camera mode (static or dynamic) for hazard area tracking
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
    """
    Get the current camera mode (static or dynamic) for hazard area tracking
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
    """Get saved safe area configuration from database."""
    return Stream().get_safe_area()


# @stream_blueprint.route("/get_current_ptz_values", methods=["POST"])
# def get_current_ptz_values():
#     try:
#         data = json.loads(request.data)
#         stream_id = data.get("streamId")

#         # stream = streams[stream_id]
#         stream = streams.get(stream_id)
#         camera_controller = stream.camera_controller

#         if camera_controller is None:
#             return tools.JsonResp(
#                 {
#                     "status": "error",
#                     "message": "Camera controller is missing!",
#                 },
#                 400,
#             )

#         current_pan, current_tilt, current_zoom = camera_controller.get_current_position()
#         # current_pan = status.Position.PanTilt.x
#         # current_tilt = status.Position.PanTilt.y
#         # current_zoom = status.Position.Zoom.x

#         return tools.JsonResp({"status": "Success", "message": "ok", "data": {"x": current_pan, "y":current_tilt, "z": current_zoom}}, 200)

#     except Exception as e:
#         print("An error occurred: ", e)
#         traceback.print_exc()
#         return tools.JsonResp({"status": "error", "message": e}, 400)


@stream_blueprint.route("/get_current_ptz_values", methods=["POST"])
def get_current_ptz_values():
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
    return Stream().save_patrol_area()


@stream_blueprint.route("/get_patrol_area", methods=["POST"])
def get_patrol_area():
    return Stream().get_patrol_area()


@stream_blueprint.route("", methods=["POST"])
def create_stream():
    return Stream().create_stream()


@stream_blueprint.route("", methods=["GET"])
def get_streams():
    """
    using query params to get either a single stream or a list of streams
    format looks something like this /api/stream?stream_id=stream1
    """

    stream_id = request.args.get("stream_id")
    return Stream().get(stream_id)


@stream_blueprint.route("/alert", methods=["GET"])
def alert():
    """
    using query params to get either a single stream or a list of streams
    format looks something like this /api/stream?stream_id=stream1
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
    """
    here we can also get default ptz location and store it (optional)

    obtain frame if stream is active
    -- get video streaming object
    -- get latest frame from the streaming object without deleting the frame

    send this frame
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
