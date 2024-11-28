# from database.db import create_db_instance

# db = create_db_instance()
from flask import current_app as app

from main.shared import streams
from main.shared import camera_controllers
from streaming.video_streaming import VideoStreaming
from utils.camera_controller import CameraController
from main import tools
import asyncio
import time
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from ptz.autotrack import PTZAutoTracker

scheduler = BackgroundScheduler()
scheduler.start()

class Stream:
    @staticmethod
    def get_all_streams():
        streams = app.db.streams.find()
        return streams
    
    @staticmethod
    async def start_stream(rtsp_link, model_name, stream_id, end_timestamp, cam_ip=None, ptz_port=None, ptz_username=None, ptz_password=None, home_pan=None, home_tilt=None, home_zoom=None):
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = all([home_pan, home_tilt, home_zoom])
        
        if stream_id in streams:
            print("Stream is already running!")
            return
        
        # Start the video stream immediately
        video_streaming = VideoStreaming(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # Schedule stop stream
        stop_time = datetime.datetime.fromtimestamp(end_timestamp)
        scheduler.add_job(Stream.stop_stream, 'date', run_date=stop_time, args=[stream_id])
        print(f"Stream {stream_id} scheduled to stop at {stop_time}.")

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
        stream = streams[stream_id]
        camera_controller = CameraController(cam_ip, ptz_port, ptz_username, ptz_password)
        stream.camera_controller = camera_controller
        # camera_controllers[stream_id] = camera_controller

        # if camera controller is initialized successfully, then we initialize auto tracker
        ptz_auto_tracker = PTZAutoTracker(cam_ip, ptz_port, ptz_username, ptz_password)
        stream.ptz_auto_tracker = ptz_auto_tracker

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
            raise RuntimeError(f"Failed to update RTSP link for stream {stream_id}: {e}")


