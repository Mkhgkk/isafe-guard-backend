import cv2
import datetime
import threading
import time
import asyncio
from collections import deque
from queue import Queue
from detection.object_detection import ObjectDetection
from utils.camera_controller import CameraController
from socket_.socketio_instance import socketio
import base64
import os


from appwrite.client import Client
from appwrite.query import Query
from appwrite.services.databases import Databases
from appwrite.id import ID

import subprocess
import requests


client = Client()
client.set_endpoint('http://172.105.209.31/v1')
client.set_project('66f4c2e6001ef89c0f5c')
client.set_key('standard_a5d6a12567fad8968cf5e2bc4482006c886d22e175e2d9bdabfea4453958462e507effc6276fc3f9b6f766bf34bf5290a9cb56d8277003a4128de039fd5a5d7299c12ea831eccc96d04c50655e5f0a7df0a5fcd80532a664649f0fb9e34cdfe33f12d91035738668f6b2bbefb7ed665c8905eb0796038981498cd4e7a9bc22aa')

databases = Databases(client)

class VideoStreaming:
    def __init__(self, rtsp_link, model_name, stream_id, ptz_autotrack=False):
        self.VIDEO = None
        self.MODEL = ObjectDetection()
        self.fps_queue = deque(maxlen=30)
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        self.frames_written = 0
        self.video_name = None

        self.frame_buffer = Queue(maxsize=10)
        self.running = False

        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name

        self.ptz_autotrack = ptz_autotrack

        # Variables to manage recording cooldown
        self.last_event_time = 0  # Track the time of the last unsafe event
        self.event_cooldown_seconds = 30  # Cooldown period in seconds

    def apply_model(self, frame, model_name):
        model = self.MODEL.models.get(model_name)
        if not model:
            raise ValueError(f"Model '{model_name}' not found!")

        results = model(frame)
        final_status = "Safe"

        if model_name == "PPE":
            final_status = self.MODEL.detect_ppe(frame, results, self.ptz_autotrack)
        elif model_name == "Ladder":
            final_status = self.MODEL.detect_ladder(frame, results)
        elif model_name == "MobileScaffolding":
            final_status = self.MODEL.detect_mobile_scaffolding(frame, results)
        elif model_name == "Scaffolding":
            final_status = self.MODEL.detect_scaffolding(frame, results)
        elif model_name == "CuttingWelding":
            final_status = self.MODEL.detect_cutting_welding(frame, results)

        return frame, final_status

    def create_video_writer(self, frame, timestamp, model_name, output_fps):
        video_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '../main/static/videos'))
        os.makedirs(video_directory, exist_ok=True)

        video_name = f"video_{self.stream_id}_{model_name}_{timestamp}.mp4"
        video_path = os.path.join(video_directory, video_name)

        height, width, _ = frame.shape

        # FFmpeg command to write raw video frames to MP4 using H.264 codec (libx264)
        command = [
            'ffmpeg',
            '-y',  # Overwrite output file if it exists
            '-f', 'rawvideo',  # Input format: raw video
            '-vcodec', 'rawvideo',  # Codec for raw video input
            '-pix_fmt', 'bgr24',  # Pixel format for OpenCV frames
            '-s', f'{width}x{height}',  # Frame size
            '-r', str(output_fps),  # Frame rate
            '-i', '-',  # Input comes from stdin (pipe)
            '-an',  # No audio
            '-c:v', 'libx264',  # Use H.264 codec
            '-preset', 'fast',  # Encoding speed preset
            '-crf', '23',  # Quality setting (lower is higher quality)
            '-pix_fmt', 'yuv420p',  # Output pixel format (needed for compatibility)
            video_path  # Output video path
        ]

        # Start the FFmpeg process
        process = subprocess.Popen(command, stdin=subprocess.PIPE)

        # Return the FFmpeg process and the video name
        return process, video_name

    def write_frames_to_ffmpeg(self, process, frame):
        try:
            # Convert the frame to bytes and write it to the FFmpeg process stdin
            process.stdin.write(frame.tobytes())
        except BrokenPipeError:
            print("FFmpeg process ended unexpectedly.")

    def finalize_video(self, process):
        if process:
            process.stdin.close()  # Close the stdin to signal FFmpeg to finish
            process.wait()  # Wait for FFmpeg to finish writing the video

    def start_stream(self):
        self.running = True
        threading.Thread(target=self.generate_frames, args=(self.rtsp_link, self.model_name), daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, args=(self.model_name,), daemon=True).start()

    def stop_streaming(self):
        self.running = False

    def generate_frames(self, rtsp_link, model_name):
        while self.running:

            video_capture = cv2.VideoCapture(rtsp_link)

            if not video_capture.isOpened():
                print(f"Error: Unable to open video stream from {rtsp_link}. Retrying in 5 seconds...")
                time.sleep(5)
                continue

            fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
            desired_width, desired_height = 1280, 720

            while self.running and video_capture.isOpened():
                ret, frame = video_capture.read()

                if not ret:
                    print(f"Failed to read from {rtsp_link}. Attempting to reconnect...")
                    video_capture.release()
                    break

                frame = cv2.resize(frame, (desired_width, desired_height))

                try:
                    self.frame_buffer.put_nowait(frame)
                except:
                    print("Frame buffer is full; dropping frame.")

            video_capture.release()
            print(f"Stream from {rtsp_link} disconnected. Reconnecting in 5 seconds...")

            if self.running:
                time.sleep(5)

    def send_watch_notification(self):
        print("Sending notification now...")
        data = {
            "phone_id": "4b91e2ca33c3119c",
            "status": "UnSafe",
            "detail": ["안전모 미착용"],
            "timestamp": str(time.time_ns())
        }
        url = "http://118.67.143.38:7000/external/camera"

        try:
            response = requests.post(url, json=data)
            # Optionally check for successful status code (200 or 201)
            if response.status_code in (200, 201):
                print("Notification sent successfully!")
            else:
                print(f"Failed to send notification. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error occurred: {e}")


    def save_event_to_database(self, frame, title, description, start_time, filename):
        timestamp_str = str(int(time.time()))
        image_filename = f"thumbnail_{timestamp_str}.jpg"

        image_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '../main/static/thumbnails'))
        os.makedirs(image_directory, exist_ok=True)

        original_height, original_width = frame.shape[:2]
        target_width = 150
        aspect_ratio = original_height / original_width
        target_height = int(target_width * aspect_ratio)
        resized_frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)

        image_path = os.path.join(image_directory, image_filename)

        ret = cv2.imwrite(image_path, resized_frame)

        if not ret:
            print("Failed to save frame as an image")
            return

        try:
            response = databases.create_document(
                database_id="isafe-guard-db",
                collection_id="670d337f001f9ab7ff34",
                document_id=ID.unique(),
                data={
                    "stream_id": self.stream_id,
                    "title": title,
                    "description": description,
                    "timestamp": int(start_time),
                    "thumbnail": image_filename,
                    "video_filename": filename
                }
            )
            print("Event saved successfully with image path:", response)

        except Exception as e:
            print(f"Error saving event to database: {e}")

    def process_and_emit_frames(self, model_name):
        process = None
        record_duration_seconds = 10  # Duration in seconds for each video segment
        frame_interval = 30           # Interval to check unsafe condition
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        start_time = None
        is_recording = False  # Flag to track if a recording is in progress
        video_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../main/static/videos/hls_segments'))

        while self.running:
            if not self.frame_buffer.empty():
                frame = self.frame_buffer.get()
                processed_frame, final_status = self.apply_model(frame, model_name)

                # Check if the frame is unsafe
                if final_status != "Safe":
                    self.unsafe_frame_count += 1

                # Update frame count and calculate FPS
                self.total_frame_count += 1
                self.fps_queue.append(time.time())
                if len(self.fps_queue) > 1:
                    time_diff = self.fps_queue[-1] - self.fps_queue[0]
                    fps = len(self.fps_queue) / time_diff if time_diff > 0 else 20.0
                else:
                    fps = 20.0
                cv2.putText(processed_frame, f"FPS: {fps:.2f}", (1100, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                # Encode the frame for streaming
                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                frame_data = buffer.tobytes()
                socketio.emit(f'frame-{self.stream_id}', {'image': frame_data}, namespace='/video', room=self.stream_id)

                # Check if we should start or continue saving the video, but only if not already recording
                if not is_recording and self.total_frame_count % frame_interval == 0:
                    unsafe_ratio = self.unsafe_frame_count / frame_interval if frame_interval else 0
                    if unsafe_ratio >= 0.7 and (time.time() - self.last_event_time) > self.event_cooldown_seconds:
                        # Start the FFmpeg process if it's not already running
                        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                        process, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
                        start_time = time.time()  # Set start_time when the recording starts
                        is_recording = True  # Set the recording flag to True
                        self.last_event_time = time.time()  # Update last event time

                        # Start a background thread to save the event to the database
                        save_thread = threading.Thread(target=self.save_event_to_database, args=(processed_frame, "Missing Head-hat", "PPE", start_time, video_name))
                        notification_thread = threading.Thread(target=self.send_watch_notification, args=())

                        save_thread.start()
                        notification_thread.start()

                        print(f"Started recording video at {timestamp}, start_time set to {start_time}")

                # Write the frame to the FFmpeg process
                if process is not None:
                    self.write_frames_to_ffmpeg(process, processed_frame)

                # Stop recording if the current video segment has reached the specified duration
                if process is not None and start_time is not None:
                    if (time.time() - start_time) >= record_duration_seconds:
                        self.finalize_video(process)
                        process = None
                        start_time = None  # Reset start_time after releasing the video writer
                        is_recording = False  # Reset the recording flag

                        print(f"Stopped recording video, total duration: {record_duration_seconds} seconds")

                # Reset the unsafe frame count for the next interval
                if self.total_frame_count % frame_interval == 0:
                    self.unsafe_frame_count = 0

            else:
                time.sleep(0.01)  # Increase sleep time slightly to reduce CPU usage

        # Release the video writer when stopping
        if process is not None:
            self.finalize_video(process)
