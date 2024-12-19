import os
import cv2
import json
import time
import asyncio
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

from socket_.socketio_instance import socketio

stream_blueprint = Blueprint("stream", __name__)

REFERENCE_FRAME_DIR = '../static/frame_refs'

@stream_blueprint.route("/start_stream", methods=['POST'])
def start_stream():
    return Stream().start()


@stream_blueprint.route("/stop_stream", methods=['POST'])
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
    
@stream_blueprint.route("/change_autotrack", methods=['POST'])
def change_autotrack():
    try:
        data = json.loads(request.data)
        stream_id = data["stream_id"]

        video_streaming = streams.get(stream_id)
        if video_streaming is None:
            return tools.JsonResp({"status": "error", "message": "Stream with the give ID is not active!"}, 400)
        video_streaming.ptz_autotrack = not video_streaming.ptz_autotrack

        if (video_streaming.camera_controller and video_streaming.ptz_auto_tracker):
            # obtain current ptz coordinates
            camera_controller = video_streaming.camera_controller
            pan, tilt, zoom = camera_controller.get_current_position()

            # set these coordinates and default position
            video_streaming.ptz_auto_tracker.update_default_position(pan, tilt, zoom)

            # emit change autotrack change
            room = f"ptz-{stream_id}"
            app.socketio.emit(f'ptz-autotrack-change', {'ptz_autotrack': video_streaming.ptz_autotrack}, namespace='/video', room=room)
            
            return tools.JsonResp({
                "status": "Success",
                "message": "Autotrack changed successfully",
                "data": {"ptz_autotrack": video_streaming.ptz_autotrack}
            }, 200)
        
        else:
            return tools.JsonResp({"status": "error", "message": "Failed to change auto tracking!"}, 400)

    except Exception as e:
        # print(video_streaming)
        print("An error occurred:", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": "wrong data format!"}, 400)
    
    
@stream_blueprint.route("/create_schedule", methods=['POST'])
    
@stream_blueprint.route("/update_stream", methods=['POST'])
def update_stream():
    return Stream().update_stream()

@stream_blueprint.route("/set_danger_zone", methods=['POST'])
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

        image_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), REFERENCE_FRAME_DIR)), file_name)
        # reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        reference_frame = cv2.imread(image_path)
        safe_area_box = coords

        # safe_area_tracker.update_safe_area(reference_frame, safe_area_box)
        safe_area_tracker = safe_area_trackers[stream_id]
        safe_area_tracker.update_safe_area(reference_frame, safe_area_box)


        # Send response
        return tools.JsonResp({
            "status": "Success",
            "message": "ok",
            "data": "ok"
        }, 200)


    except Exception as e: 
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)
    

@stream_blueprint.route("", methods=['POST'])
def create_stream():
    return Stream().create_stream()

@stream_blueprint.route("", methods=['GET'])
def get_streams():
    """
        using query params to get either a single stream or a list of streams
        format looks something like this /api/stream?stream_id=stream1
    """

    stream_id = request.args.get('stream_id')
    return Stream().get(stream_id)


@stream_blueprint.route("/alert", methods=['GET'])
def alert():
    """
        using query params to get either a single stream or a list of streams
        format looks something like this /api/stream?stream_id=stream1
    """

    stream_id = request.args.get('stream_id')

    socketio.emit(f'alert-{stream_id}', {'type': "intrusion"}, namespace='/video', room=stream_id)
    
    return tools.JsonResp({"data": "ok"}, 200)


    
@stream_blueprint.route("/get_current_frame", methods=['POST'])
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
        stream_id = data.get('stream_id')

        file_name = None

        stream = streams[stream_id]
        if stream is not None:
            frame_buffer = stream.frame_buffer

            while file_name is None:
                # with frame_buffer.mutex:
                if frame_buffer.qsize() > 0:
                    current_frame = frame_buffer.queue[-1]

                    ret, buffer = cv2.imencode('.jpg', current_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    # current_frame = buffer.tobytes()

                    current_frame_bytes = buffer.tobytes()

                    file_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), REFERENCE_FRAME_DIR))
                    os.makedirs(file_directory, exist_ok=True)

                    file_name = f"frame_{int(time.time())}_{stream_id}.jpg"
                    file_path = os.path.join(file_directory, file_name)

                    with open(file_path, 'wb') as file:
                        file.write(current_frame_bytes)
        else:
            # stream is not active
            return tools.JsonResp({
                "status": "Error",
                "message": "Stream inactive!"
            }, 404)

        # Send response
        return tools.JsonResp({
            "status": "Success",
            "message": "ok",
            "data": file_name
        }, 200)


    except Exception as e: 
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": str(e)}, 400)