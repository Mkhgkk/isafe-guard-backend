import cv2
import datetime
import threading
import time
import os
import subprocess
import requests
from collections import deque
from flask import current_app as app
from queue import Queue
from detection.object_detection import ObjectDetection
from socket_.socketio_instance import socketio
from intrusion import detect_intrusion
from intrusion.auto import SafeAreaTracker
from main.shared import safe_area_trackers
from main.event.model import Event
from config import FRAME_HEIGHT, FRAME_WIDTH, RECONNECT_WAIT_TIME_IN_SECS, STATIC_DIR

# EVENT_VIDEO_DIR = '../main/static/videos'
# EVENT_THUMBNAIL_DIR = '../main/static/thumbnails'

RTMP_MEDIA_SERVER = os.getenv('RTMP_MEDIA_SERVER', 'rtmp://localhost:1935')

class StreamManager:
    def __init__(self, rtsp_link, model_name, stream_id, ptz_autotrack=False):
        self.DETECTOR = ObjectDetection(model_name)
        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        self.fps_queue = deque(maxlen=30)
        self.frame_buffer = Queue(maxsize=10)
        self.running = False
        self.stop_event = threading.Event()

        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        self.frames_written = 0
        self.video_name = None
        self.last_event_time = 0 
        self.event_cooldown_seconds = 30  

        self.ptz_autotrack = ptz_autotrack
        self.ptz_auto_tracker = None

        self.safe_area_tracker = SafeAreaTracker()
        safe_area_trackers[stream_id] = self.safe_area_tracker

        self.camera_controller = None

        self.EVENT_VIDEO_DIR = os.path.join(STATIC_DIR, self.stream_id, "videos")
        self.EVENT_THUMBNAIL_DIR = os.path.join(STATIC_DIR, self.stream_id, "thumbnails")


    def apply_model(self, frame, model_name):
        model = self.DETECTOR.model

        results = model(frame)
        final_status = "Safe"
        reasons = []
        bboxes = None

        if model_name == "PPE":
            final_status, reasons, bboxes = self.DETECTOR.detect_ppe(frame, results, self.ptz_autotrack)
        elif model_name == "Ladder":
            final_status = self.DETECTOR.detect_ladder(frame, results)
        elif model_name == "MobileScaffolding":
            final_status = self.DETECTOR.detect_mobile_scaffolding(frame, results)
        elif model_name == "Scaffolding":
            final_status, reasons = self.DETECTOR.detect_scaffolding(frame, results)
        elif model_name == "Fire":
            final_status, reasons = self.DETECTOR.detect_fire_smoke(frame, results)
        elif model_name == "CuttingWelding":
            final_status = self.DETECTOR.detect_cutting_welding(frame, results)

        # return frame, final_status, [reasons], bboxes
        return frame, final_status, reasons, bboxes

    def create_video_writer(self, frame, timestamp, model_name, output_fps):
        video_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), self.EVENT_VIDEO_DIR))
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
        self.stop_event.clear()
        threading.Thread(target=self.generate_frames, args=(self.rtsp_link, self.model_name), daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, args=(self.model_name,), daemon=True).start()

    def stop_streaming(self):
        self.running = False
        self.stop_event.set()

    def generate_frames(self, rtsp_link, model_name):
        # while self.running:
        while not self.stop_event.is_set():

            video_capture = cv2.VideoCapture(rtsp_link)

            if not video_capture.isOpened():
                print(f"Error: Unable to open video stream from {rtsp_link}. Retrying in 5 seconds...")
                time.sleep(RECONNECT_WAIT_TIME_IN_SECS)
                continue

            fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
            # desired_width, desired_height = 1280, 720

            # while self.running and video_capture.isOpened():
            while not self.stop_event.is_set() and video_capture.isOpened():
                ret, frame = video_capture.read()

                if not ret:
                    print(f"Failed to read from {rtsp_link}. Attempting to reconnect...")
                    video_capture.release()
                    break

                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

                try:
                    self.frame_buffer.put_nowait(frame)
                except:
                    # print("Frame buffer is full; dropping frame.")
                    pass

            video_capture.release()
            print(f"Stream from {rtsp_link} disconnected. Reconnecting in 5 seconds...")

            # if self.running:
            if not self.stop_event.is_set():
                time.sleep(RECONNECT_WAIT_TIME_IN_SECS)

    def send_watch_notification(self, reasons=["Wear helmet"]):
        data = {
            "phone_id": "4b91e2ca33c3119c",
            "status": "UnSafe",
            # "detail": ["안전모 미착용"],
            # "detail": [reasons] if len(reasons ==1) else reasons,
            "detail": reasons,
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


    def save_event_to_database(self, frame, reasons, model_name, start_time, filename):
        timestamp_str = str(int(time.time()))
        image_filename = f"thumbnail_{timestamp_str}.jpg"

        image_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), self.EVENT_THUMBNAIL_DIR))
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
            data={
                "stream_id": self.stream_id,
                "reasons": reasons,
                "model_name": model_name,
                "timestamp": int(start_time),
                "thumbnail": image_filename,
                "video_filename": filename
            }
            
            response = Event().create_event(data)
            print("Event saved successfully: ", response)
                


        except Exception as e:
            print(f"Error saving event to database: {e}")

    

    def start_ffmpeg_process(self):
        # ffmpeg_command = [
        #     'ffmpeg',
        #     '-y',                        # Overwrite output files
        #     '-f', 'rawvideo',            # Input format
        #     '-vcodec', 'rawvideo',       # Video codec
        #     '-pix_fmt', 'bgr24',         # Pixel format (OpenCV uses BGR)
        #     '-s', '1280x720',            # Frame size
        #     '-r', '20',                  # Frame rate
        #     '-i', '-',                   # Input from stdin
        #     '-c:v', 'libx264',           # Output codec
        #     '-preset', 'ultrafast',      # Encoding speed
        #     '-f', 'flv',                 # Output format
        #     f'{RTMP_MEDIA_SERVER}/live/{self.stream_id}'  # MediaMTX RTMP URL
        # ]
        # return subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)
        gst_command = [
            "gst-launch-1.0",
            "fdsrc",
            "!",
            "videoparse",
            "width=1280",
            "height=720",
            "framerate=30/1",
            "format=bgr",             # matches bgr24 input
            "!",
            "videoconvert",
            "!",
            "x264enc",
            "tune=zerolatency",
            "speed-preset=ultrafast", # similar to -preset ultrafast in FFmpeg
            "!",
            "flvmux",
            "streamable=true",
            "!",
            "rtmpsink",
            f"location={RTMP_MEDIA_SERVER}/live/{self.stream_id}"
        ]
        
        return subprocess.Popen(gst_command, stdin=subprocess.PIPE)

    def process_and_emit_frames(self, model_name):
        process = None
        record_duration_seconds = 10  # Duration in seconds for each video segment
        frame_interval = 30           # Interval to check unsafe condition
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        start_time = None
        is_recording = False  # Flag to track if a recording is in progress

        # Start FFmpeg process
        ffmpeg_process = self.start_ffmpeg_process()

        while not self.stop_event.is_set():
            if not self.frame_buffer.empty():
                frame = self.frame_buffer.get()
                transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
                processed_frame, final_status, reasons, person_bboxes = self.apply_model(frame, model_name)
                processed_frame = self.safe_area_tracker.draw_safe_area_on_frame(processed_frame, transformed_hazard_zones)

                # Check for instrusion
                intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
                if len(intruders) > 0:
                    final_status = "Unsafe"
                    # update reasons
                    reasons.append("intrusion")
                    socketio.emit(f'alert-{self.stream_id}', {'type': "intrusion"}, namespace='/video', room=self.stream_id)

                # PTZ auto-tracker
                if self.ptz_autotrack and self.ptz_auto_tracker:
                    self.ptz_auto_tracker.track(1280, 720, person_bboxes)

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

                # Send the frame to FFmpeg
                try:
                    ffmpeg_process.stdin.write(processed_frame.tobytes())
                except BrokenPipeError:
                    print("FFmpeg process has stopped unexpectedly. Restarting...")
                    ffmpeg_process.stdin.close()
                    ffmpeg_process.wait()
                    ffmpeg_process = self.start_ffmpeg_process()

                # Handle recording logic (if necessary)
                if not is_recording and self.total_frame_count % frame_interval == 0:
                    unsafe_ratio = self.unsafe_frame_count / frame_interval if frame_interval else 0
                    if unsafe_ratio >= 0.7 and (time.time() - self.last_event_time) > self.event_cooldown_seconds:
                        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                        process, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
                        start_time = time.time()  # Set start_time when the recording starts
                        is_recording = True
                        self.last_event_time = time.time()

                        save_thread = threading.Thread(target=self.save_event_to_database, args=(processed_frame, list(set(reasons)), self.model_name, start_time, video_name))
                        notification_thread = threading.Thread(target=self.send_watch_notification, args=(reasons))

                        save_thread.start()
                        print(f"Started recording video at {timestamp}, start_time set to {start_time}")

                # # Stop recording if the current video segment has reached the specified duration
                # if process is not None and start_time is not None:
                #     if (time.time() - start_time) >= record_duration_seconds:
                #         self.finalize_video(process)
                #         process = None
                #         start_time = None
                #         is_recording = False
                #         print(f"Stopped recording video, total duration: {record_duration_seconds} seconds")

                # # Reset the unsafe frame count for the next interval
                # if self.total_frame_count % frame_interval == 0:
                #     self.unsafe_frame_count = 0

                 # Write frames continuously if recording
                 
                if is_recording and process is not None:
                    try:
                        process.stdin.write(processed_frame.tobytes())
                    except BrokenPipeError:
                        print("Recording process has stopped unexpectedly.")
                        is_recording = False
                        self.finalize_video(process)
                        process = None

                # Stop recording if the current video segment has reached the specified duration
                if is_recording and process is not None and start_time is not None:
                    if (time.time() - start_time) >= record_duration_seconds:
                        self.finalize_video(process)
                        process = None
                        start_time = None
                        is_recording = False
                        print(f"Stopped recording video, total duration: {record_duration_seconds} seconds")

                # Reset the unsafe frame count for the next interval
                if self.total_frame_count % frame_interval == 0:
                    self.unsafe_frame_count = 0

            else:
                time.sleep(0.01)  # Increase sleep time slightly to reduce CPU usage

        # Release the FFmpeg process
        if ffmpeg_process:
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()


