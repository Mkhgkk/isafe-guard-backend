from flask import current_app as app
from flask import Response
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
from appwrite.id import ID

import asyncio
import os
import cv2
import time

# from intrusion.auto import safe_area_box, reference_frame
from intrusion.auto import SafeAreaTracker
from urllib.parse import urlparse

# safe_area_tracker = SafeAreaTracker()
from main.shared import safe_area_trackers



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
    

@stream_blueprint.route("/stop_stream", methods=['POST'])
def stop_stream():
    try: 
        data = json.loads(request.data)
        stream_id = data["stream_id"]

        video_streaming = streams[stream_id]
        video_streaming.stop_streaming()

        del streams[stream_id]
        del camera_controllers[stream_id]

        return tools.JsonResp({
            "status": "Success",
            "message": "Detector stopped successfully",
            "data": data
        }, 200)

    except Exception as e:
        return tools.JsonResp({"status": "error", "message": "wrong data format!"}, 400)
    

def stream_video(file_path):
    def generate():
        with open(file_path, "rb") as video_file:
            data = video_file.read(1024 * 1024)  # Stream in chunks of 1MB
            while data:
                yield data
                data = video_file.read(1024 * 1024)
    return Response(generate(), mimetype="video/mp4")
    

@stream_blueprint.route("/video_playback/<filename>", methods=['GET'])
def stream_file(filename):
    file_path = os.path.join('/home/Mkhgkk/Projects/Monitoring/src/main/static/videos', filename)
    return stream_video(file_path)
    

    
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
def create_schedule():
    try:
        data = json.loads(request.data)
        stream_document_id = data['stream_document_id']

        # Get stream from database
        stream_document = app.databases.get_document(
            database_id="isafe-guard-db",
            collection_id="66f504260003d64837e5",
            document_id=stream_document_id
        )

        # description: data.description,
        #   stream_id: data.stream_id,
        #   start_timestamp: getUnixTimestamp(data.startDate, data.startTime),
        #   end_timestamp: getUnixTimestamp(data.endDate, data.endTime),
        #   location: data.location,
        #   model_name: data.model_name,

        # Create a schedule
        response = app.databases.create_document(
            database_id="isafe-guard-db",
            collection_id="66fa20d600253c7d4503",
            document_id=ID.unique(),
            data={"stream_id": stream_document['stream_id'],
                  "start_timestamp": data['start_timestamp'],
                  "end_timestamp": data['end_timestamp'],
                  "location": data['location'],
                  "model_name": data['model_name']
                  }
        )

        # Start stream
        # Stream.start_stream(stream_document['rtsp_link'], response['model_name'], stream_document['stream_id'], response['end_timestamp'], stream_document['cam_ip'], stream_document['ptz_port'], stream_document['ptz_username'], stream_document['ptz_password'])
        asyncio.run(Stream.start_stream(stream_document['rtsp_link'], response['model_name'], stream_document['stream_id'], response['end_timestamp'], stream_document['cam_ip'], stream_document['ptz_port'], stream_document['ptz_username'], stream_document['ptz_password']))
        
        return tools.JsonResp({
            "status": "Success",
            "message": "Schedule created successfully",
            "data": response
        }, 200)
    except Exception as e: 
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)
    
@stream_blueprint.route("/delete_schedule", methods=['POST'])
def delete_schedule():
    try:
        # Schedule document
        data = json.loads(request.data)
        stream_id = data['stream_id']
        schedule_document_id = data['$id']

        # Check if stream is running
        stream = streams.get(stream_id)
        # Stop stream
        if stream is not None:
            Stream.stop_stream(stream_id)

        # Delete schedule
        response = app.databases.delete_document(
            database_id="isafe-guard-db",
            collection_id="66fa20d600253c7d4503",
            document_id=schedule_document_id
        )

        print("Document deleted successfully.")
        

        # Send response
        return tools.JsonResp({
            "status": "Success",
            "message": "Schedule deleted successfully",
            "data": response
        }, 200)


    except Exception as e:
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)
    

@stream_blueprint.route("/update_stream", methods=['POST'])
def update_stream():
    try:
        data = json.loads(request.data)
        stream_id = data['stream_id']
        rtsp_link = data['rtsp_link']
        stream_document_id = data['$id']
        
        # Check if stream is running and stop  it before updating
        stream = streams.get(stream_id)
        if stream is not None:
            # if stream.rtsp_link != rtsp_link:
            #     Stream.update_rtsp_link(stream_id, rtsp_link)
            # print(stream)
            stream.stop_streaming()

        response = app.databases.update_document(
            database_id="isafe-guard-db",
            collection_id="66f504260003d64837e5",
            document_id=stream_document_id,
            data=data
        )

        print("Document updated successfully.")

        # Send response
        return tools.JsonResp({
            "status": "Success",
            "message": "Stream updated successfully",
            "data": response
        }, 200)


    except Exception as e: 
        print("An error occurred: ", e)
        traceback.print_exc()
        return tools.JsonResp({"status": "error", "message": e}, 400)
    



@stream_blueprint.route("/set_danger_zone", methods=['POST'])
def set_danger_zone():
    # get image data
    # get list of of coordinates
    # get current ptz location (consider that the camera can be moved)
    try:
        data = json.loads(request.data)
        image = data.get("image")
        coords = data.get("coords")
        stream_id = data.get("streamId")
        print(data)

        parsed_url = urlparse(image)
        path = parsed_url.path
        file_name = os.path.basename(path)

        image_path = os.path.join('main/static/frame_refs', file_name)
        reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
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
    
@stream_blueprint.route("/get_current_frame", methods=['POST'])
def get_current_frame():
    # here we can also get default ptz location and store it (optional)

    # obtain frame if stream is active
    # -- get video streaming object
    # -- get latest frame from the streaming object without deleting the frame

    # send this frame 

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

                    file_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '../static/frame_refs'))
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