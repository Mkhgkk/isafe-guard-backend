from flask import current_app as app
from flask import Flask, request
import json
from .model import Stream
from main import tools

from flask import Blueprint

stream_blueprint = Blueprint("stream", __name__)

import traceback

from main.shared import streams
from streaming.video_streaming import VideoStreaming
from main.shared import camera_controllers
from utils.camera_controller import CameraController

# @app.route('/api/get_all_streams', methods=['GET'])
@stream_blueprint.route("/get_all", methods=["GET"])
def get_all_streams():
    streams = Stream.get_all_streams()
    resp = tools.JsonResp(list(streams), 200)
    return resp

@stream_blueprint.route("/start_stream", methods=['POST'])
def start_stream():
    try:
        data = json.loads(request.data)
        rtsp_link = data["rtsp_link"]
        model_name = data["model_name"]
        stream_id = data["stream_id"]
        ptz_autotrack = data.get("ptz_autotrack", None)


        # Check if a stream with the same stream_id already exists
        if stream_id in streams:
            return tools.JsonResp({
                "status": "error",
                "message": f"Stream with id {stream_id} already exists!"
            }, 400)
        
        video_streaming = VideoStreaming(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        supports_ptz = data["supports_ptz"]
        if supports_ptz:
            cam_ip = data["cam_ip"]
            ptz_port = data["ptz_port"]
            ptz_username = data["ptz_username"]
            ptz_password = data["ptz_password"]

            camera_controller = CameraController(cam_ip, ptz_port, ptz_username, ptz_password)
            camera_controllers[stream_id] = camera_controller

        return tools.JsonResp({
            "status": "Success",
            "message": "Detector started successfully",
            "data": data,
            "supports_ptz": supports_ptz
        }, 200)

        
    except Exception as e:
        print("An error occurred:", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": "wrong data format!"}, 400)


# @app.route('/api/start_stream_', methods=['POST'])
# def start_stream_():
    if request.is_json:
        data = request.get_json()
        rtsp_link = data["rtsp_link"]
        model_name = data["model_name"]
        stream_id = data["stream_id"]
        ptz_autotrack= data["ptz_autotrack"]

        # Check if a stream with the same stream_id already exists
        if stream_id in streams:
            return jsonify({
                "status": "error",
                "message": f"Stream with id {stream_id} already exists!"
            }), 400


        video_streaming = VideoStreaming(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        supports_ptz = data["supports_ptz"]
        if supports_ptz:
            cam_ip = data["cam_ip"]
            ptz_port = data["ptz_port"]
            ptz_username = data["ptz_username"]
            ptz_password = data["ptz_password"]

            camera_controller = CameraController(cam_ip, ptz_port, ptz_username, ptz_password)
            camera_controllers[stream_id] = camera_controller

        response = {
            "status": "Success",
            "message": "Detector started successfully",
            "data": data,
            "supports_ptz": supports_ptz
        }

        return jsonify(response), 200

    else:
        return jsonify({"status": "error", "message": "wrong data format!"}), 400