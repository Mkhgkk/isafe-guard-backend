from flask import Flask, jsonify, request, render_template
from streaming.video_streaming import VideoStreaming
from utils.camera_controller import CameraController

from streams import streams
from camera_controllers import camera_controllers


# streams = {}
# camera_controllers = {}

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data', methods=['POST'])
def receive_data():
    if request.is_json:
        data = request.get_json()
        print(f"Received data: {data}")
        response = {
            "status": "success",
            "message": "Data received successfully",
            "data": data
        }
        return jsonify(response), 200
    else:
        return jsonify({"status": "error", "message": "Request data must be JSON"}), 400

@app.route('/api/start_stream', methods=['POST'])
def start_stream():
    if request.is_json:
        data = request.get_json()
        rtsp_link = data["rtsp_link"]
        model_name = data["model_name"]
        stream_id = data["stream_id"]
        ptz_autotrack= data["ptz_autotrack"]

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

@app.route('/api/stop_stream', methods=['POST'])
def stop_stream():
    if request.is_json:
        data = request.get_json()
        stream_id = data["stream_id"]

        video_streaming = streams[stream_id]
        video_streaming.stop_streaming()

        del streams[stream_id]
        del camera_controllers[stream_id]

        response = {
            "status": "Success",
            "message": "Detector stopped successfully",
            "data": data
        }

        return jsonify(response), 200

    else:
        return jsonify({"status": "error", "message": "wrong data format!"}), 400
    
@app.route('/api/change_autotrack', methods=['POST'])
def change_autotrack():
    if request.is_json:
        data = request.get_json()
        stream_id = data["stream_id"]

        video_streaming = streams[stream_id]
        video_streaming.ptz_autotrack = not video_streaming.ptz_autotrack

        # emit change autotrack change
        room = f"ptz-{stream_id}"
        app.socketio.emit(f'ptz-autotrack-change', {'ptz_autotrack': video_streaming.ptz_autotrack}, namespace='/video', room=room)

        response = {
            "status": "Success",
            "message": "Autotrack changed successfully",
            "data": {"ptz_autotrack": video_streaming.ptz_autotrack}
        }

        return jsonify(response), 200

    else:
        return jsonify({"status": "error", "message": "wrong data format!"}), 400
