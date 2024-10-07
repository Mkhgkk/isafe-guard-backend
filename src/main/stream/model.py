# from database.db import create_db_instance

# db = create_db_instance()
from flask import current_app as app

from main.shared import streams
from main.shared import camera_controllers
from streaming.video_streaming import VideoStreaming
from utils.camera_controller import CameraController
from main import tools
import asyncio

class Stream:
    @staticmethod
    def get_all_streams():
        streams = app.db.streams.find()
        return streams
    
    @staticmethod
    async def start_stream(rtsp_link, model_name, stream_id, cam_ip=None, ptz_port=None, ptz_username=None, ptz_password=None, home_pan=None, home_tilt=None, home_zoom=None):
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = all([home_pan, home_tilt, home_zoom])
        
        if stream_id in streams:
            print("Stream is already running!")
            return
        
        # Start the video stream immediately
        video_streaming = VideoStreaming(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # Asynchronously configure PTZ to avoid blocking the loop
        if supports_ptz:
            try:
                # Run the long-running CameraController initialization asynchronously
                await asyncio.to_thread(Stream.initialize_camera_controller, cam_ip, ptz_port, ptz_username, ptz_password, stream_id)
            except Exception as e:
                print(f"Error initializing PTZ for stream {stream_id}: {e}")

    @staticmethod
    def initialize_camera_controller(cam_ip, ptz_port, ptz_username, ptz_password, stream_id):
        """This function will be executed in a background thread to avoid blocking the loop."""
        camera_controller = CameraController(cam_ip, ptz_port, ptz_username, ptz_password)
        camera_controllers[stream_id] = camera_controller
        print(f"PTZ configured for stream {stream_id}.")
    
    # @staticmethod
    # def start_stream(rtsp_link, model_name, stream_id, cam_ip=None, ptz_port=None, ptz_username=None, ptz_password=None, home_pan=None, home_tilt=None, home_zoom=None):
    #     supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
    #     ptz_autotrack = all([home_pan, home_tilt, home_zoom])
        
    #     if stream_id in streams:
    #         print("Stream is already running!")
    #         return
        
    #     video_streaming = VideoStreaming(rtsp_link, model_name, stream_id, ptz_autotrack)
    #     video_streaming.start_stream()
    #     streams[stream_id] = video_streaming


    #     # configure ptz
    #     if supports_ptz:
    #         cam_ip = cam_ip
    #         ptz_port = ptz_port
    #         ptz_username = ptz_username
    #         ptz_password = ptz_password

    #         camera_controller = CameraController(cam_ip, ptz_port, ptz_username, ptz_password)
    #         camera_controllers[stream_id] = camera_controller

    @staticmethod
    def stop_stream(stream_id):
        stream_id = stream_id

        video_streaming = streams[stream_id]
        video_streaming.stop_streaming()

        del streams[stream_id]
        del camera_controllers[stream_id]
