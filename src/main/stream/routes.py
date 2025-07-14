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

stream_blueprint = Blueprint("stream", __name__)

REFERENCE_FRAME_DIR = "../static/frame_refs"
NAMESPACE = "/default"


@stream_blueprint.route("/start_stream", methods=["POST"])
def start_stream():
    return Stream().start()


@stream_blueprint.route("/stop_stream", methods=["POST"])
def stop_stream():
    return Stream().stop()


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
                {"status": "error", "message": "This stream does not support ptz auto tracking!"}, 400
            ) 
        
        video_streaming.ptz_autotrack = not video_streaming.ptz_autotrack

        # if video_streaming.ptz_autotrack:
        #     if video_streaming.camera_controller and video_streaming.ptz_auto_tracker:
        #         # obtain current ptz coordinates
        #         camera_controller = video_streaming.camera_controller
        #         pan, tilt, zoom = camera_controller.get_current_position()

        #         # set these coordinates and default position
        #         video_streaming.ptz_auto_tracker.update_default_position(pan, tilt, zoom)
        # else: 
        #     # stop stop tracking
        #     if video_streaming.ptz_auto_tracker:
        #         video_streaming.ptz_auto_tracker.reset_camera_position()
            

        # Start patrol
        if video_streaming.ptz_autotrack:
            if video_streaming.camera_controller and video_streaming.ptz_auto_tracker:
                # obtain current ptz coordinates
                camera_controller = video_streaming.camera_controller
                pan, tilt, zoom = camera_controller.get_current_position()

                # set these coordinates and default position
                video_streaming.ptz_auto_tracker.update_default_position(pan, tilt, zoom)

                # video_streaming.ptz_auto_tracker.set_patrol_parameters(x_step=0.02, y_step=0.05, dwell_time=3.0)
                # video_streaming.ptz_auto_tracker.start_patrol(direction="vertical")

                # TODO:
                # sort yMin and yMax to work with both cameras

                video_streaming.ptz_auto_tracker.set_patrol_area({'zMin': 0.04, 'zMax': 0.088, 'xMin': -0.43849999999999967, 'xMax': 0.6418333333333334, 'yMin': 1, 'yMax': 0.01904761904761898})
                # video_streaming.ptz_auto_tracker.set_patrol_area({'zMin': 0.0700000152, 'zMax': 0.150000021, 'xMin': -0.485888898, 'xMax': 0.462777704, 'yMin': -1, 'yMax': 0.377272725})
                # video_streaming.ptz_auto_tracker.set_patrol_area({'zMin': 0.0700000152, 'zMax': 0.150000021, 'xMin': -0.485888898, 'xMax': 0.462777704, 'yMin': 0.377272725, 'yMax': -1}) # working patrol area for unv camrea
                video_streaming.ptz_auto_tracker.set_patrol_parameters(focus_max_zoom=1.0)

                # video_streaming.ptz_auto_tracker.configure_patrol_grid(3, 2)
                video_streaming.ptz_auto_tracker.set_patrol_parameters(x_positions=10, y_positions=4, dwell_time=1.5, zoom_level=0.04)
                video_streaming.ptz_auto_tracker.start_patrol("horizontal")

        else:
            video_streaming.ptz_auto_tracker.stop_patrol()
            video_streaming.ptz_auto_tracker.reset_camera_position()



        # emit change autotrack change
        room = f"ptz-{stream_id}"
        data = {"ptz_autotrack": video_streaming.ptz_autotrack}
        emit_event(event_type=EventType.PTZ_AUTOTRACK, data=data, room=room )

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


@stream_blueprint.route("/create_schedule", methods=["POST"])
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
    """
    try:
        data = json.loads(request.data)
        image = data.get("image")
        coords = data.get("coords")
        stream_id = data.get("streamId")
        print(data)

        parsed_url = urlparse(image)
        path = parsed_url.path
        file_name = os.path.basename(path)

        image_path = os.path.join(
            os.path.dirname(__file__), REFERENCE_FRAME_DIR, file_name
        )
        # reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        reference_frame = cv2.imread(image_path)
        safe_area_box = coords

        # safe_area_tracker.update_safe_area(reference_frame, safe_area_box)
        safe_area_tracker = safe_area_trackers[stream_id]
        safe_area_tracker.update_safe_area(reference_frame, safe_area_box)

        # Send response
        return tools.JsonResp({"status": "Success", "message": "ok", "data": "ok"}, 200)

    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)

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
            app.logger.warning(f"Attempted to get PTZ for non-existent or inactive stream_id: {stream_id}")
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found or is not active.",
                },
                404, # Not Found is a suitable status code here
            )
        # --- End Check ---

        camera_controller = stream.camera_controller

        # --- Check specifically if the camera controller exists for this stream ---
        if camera_controller is None:
            app.logger.warning(f"Camera controller is missing for active stream_id: {stream_id}")
            return tools.JsonResp(
                {
                    "status": "error",
                    "message": f"Camera controller not available for stream '{stream_id}'. PTZ control might not be enabled.",
                },
                400, # Bad Request or perhaps 501 Not Implemented / 503 Service Unavailable
            )
        # --- End Check ---

        current_pan, current_tilt, current_zoom = camera_controller.get_current_position()

        return tools.JsonResp({"status": "Success", "message": "ok", "data": {"x": current_pan, "y":current_tilt, "z": current_zoom}}, 200)

    except json.JSONDecodeError:
        app.logger.error("Failed to decode JSON data in /get_current_ptz_values request.")
        return tools.JsonResp({"status": "error", "message": "Invalid JSON data format."}, 400)
    except Exception as e:
        # Use app.logger for logging within Flask is standard practice
        app.logger.error(f"An error occurred in /get_current_ptz_values for stream_id '{stream_id if 'stream_id' in locals() else 'unknown'}': {e}")
        app.logger.error(traceback.format_exc()) # Log the full traceback
        # --- Convert exception to string for JSON response ---
        error_message = str(e)
        return tools.JsonResp({"status": "error", "message": f"An unexpected error occurred: {error_message}"}, 500) # 
    
@stream_blueprint.route("/save_patrol_area", methods=["POST"])
def save_patrol_area():
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

        
        if video_streaming.ptz_auto_tracker is not None:
            patrol_area= data.get("patrol_area")
            
            video_streaming.ptz_auto_tracker.set_patrol_area(patrol_area)
            logging.info(f"patrol_rea: {video_streaming.ptz_auto_tracker.patrol_area}")
            # pass

        # other data
        # logging.info(f"RECEIVED DATA: {data}")
        # INFO:root:RECEIVED DATA: {'stream_id': 'test_outside', 'patrol_area': {'zMin': 0.0699310303, 'zMax': 0.0699310303, 'xMin': 0.274833322, 'xMax': 0.274833322, 'yMin': -1, 'yMax': -1}}

        return tools.JsonResp({"status": "Success", "message": "ok", "data": "ok"}, 200)
    
    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)

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

    emit_dynamic_event(base_event_type=EventType.ALERT, identifier=stream_id, data=data, room=room )

    return tools.JsonResp({"data": "ok"}, 200)


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

                    ret, buffer = cv2.imencode(
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
