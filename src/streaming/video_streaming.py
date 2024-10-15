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


client = Client()
client.set_endpoint('http://192.168.0.10/v1')
client.set_project('66f4c2e6001ef89c0f5c')
client.set_key('standard_f6ffca3b91315e5263932317123368335466126c2bb58bf4201b64c9c3768ab3f364eabe0f7ba852fa24876c624393b306ce9a3f71db9c8fa951526a39e49721c80812d477196faad02d282ea51962a823c02f4580c1c95c67e6dba054653fa4d094a99ce4cb1a31ce52c57dbda6b925168446dd879de1e1d6321f0fa2f88cbd')

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

    

    def process_video(self, snap, model_name, out, video_count, result_queue):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if self._detect:
            if out is None:
                fps = self.VIDEO.get(cv2.CAP_PROP_FPS) or 20
                out, self.video_name = self.create_video_writer(snap, timestamp, model_name, fps)
            snap, timestamp, final_status, inference_time = self.MODEL.detectObj(snap, timestamp, model_name)
            self.total_frame_count += 1
            if final_status == "UnSafe" and out is not None:
                out.write(snap)
                self.unsafe_frame_count += 1
                self.frames_written += 1

        result_queue.put((snap, out, self.total_frame_count, timestamp, self.video_name))


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
        video_name1 = f"/home/Mkhgkk/Projects/Monitoring/src/main/static/videos/video_{model_name}_{timestamp}.mp4"
        # video_name1 = f"./static/unsafe/video_{model_name}_{timestamp}.mp4"
        video_name = f"video_{self.stream_id}_{model_name}_{timestamp}.mp4"
        height, width, _ = frame.shape
        # fourcc = cv2.VideoWriter_fourcc(*"avc1")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # Use mp4v codec
        return cv2.VideoWriter(video_name1, fourcc, output_fps, (width, height)), video_name

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
            time.sleep(5)

    # def process_and_emit_frames(self, model_name):
    #     while self.running:
    #         if not self.frame_buffer.empty():
    #             frame = self.frame_buffer.get()
    #             processed_frame, final_status = self.apply_model(frame, model_name)

    #             self.fps_queue.append(time.time())
    #             fps = len(self.fps_queue) / (self.fps_queue[-1] - self.fps_queue[0]) if len(self.fps_queue) > 1 else 0.0
    #             cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #             ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 20])
    #             frame_data = buffer.tobytes()

    #             socketio.emit(f'frame-{self.stream_id}', {'image': frame_data}, namespace='/video', room=self.stream_id)
    #         else:
    #             time.sleep(0.01)

    def save_event_to_database(self, frame, title, description, start_time, filename):

        timestamp_str = str(int(time.time()))
        image_filename = f"thumbnail_{timestamp_str}.jpg"

        image_directory = "/home/Mkhgkk/Projects/Monitoring/src/main/static/thumbnails"  # Update this path as needed
        os.makedirs(image_directory, exist_ok=True)

        image_path = os.path.join(image_directory, image_filename)

        ret = cv2.imwrite(image_path, frame)

        if not ret:
            print("Failed to save frame as an image")
            return

        try:
            # Step 2: Save the event data including the image path to the database
            response = databases.create_document(
                database_id="isafe-guard-db",
                collection_id="670d337f001f9ab7ff34",
                document_id=ID.unique(),
                data={
                    "stream_id": self.stream_id,
                    "title": title,
                    "description": description,
                    "timestamp": int(start_time),
                    "thumbnail":  image_filename,  # Save the path to the saved image
                    "video_filename": filename
                }
            )
            print("Event saved successfully with image path:", response)

        except Exception as e:
            print(f"Error saving event to database: {e}")



    def process_and_emit_frames(self, model_name):
        out = None
        record_duration_seconds = 10  # Duration in seconds for each video segment
        frame_interval = 30           # Interval to check unsafe condition
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        start_time = None
        is_recording = False  # Flag to track if a recording is in progress

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
                cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                # Encode the frame for streaming
                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 20])
                frame_data = buffer.tobytes()
                socketio.emit(f'frame-{self.stream_id}', {'image': frame_data}, namespace='/video', room=self.stream_id)

                # Check if we should start or continue saving the video, but only if not already recording
                if not is_recording and self.total_frame_count % frame_interval == 0:
                    unsafe_ratio = self.unsafe_frame_count / frame_interval if frame_interval else 0
                    if unsafe_ratio >= 0.7:
                        # Create a video writer if it's not already created
                        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                        out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
                        start_time = time.time()  # Set start_time when the recording starts
                        is_recording = True  # Set the recording flag to True
                        # TODO: save this event to database
                        self.save_event_to_database(processed_frame, "Missing Head-hat", "PPE", start_time, video_name)
                        print(f"Started recording video at {timestamp}, start_time set to {start_time}")

                # Write the frame to the video file if the writer is initialized
                if out is not None:
                    out.write(processed_frame)

                # Stop recording if the current video segment has reached the specified duration
                # Check this only if out is initialized and a start_time exists
                if out is not None and start_time is not None:
                    if (time.time() - start_time) >= record_duration_seconds:
                        out.release()
                        out = None
                        start_time = None  # Reset start_time after releasing the video writer
                        is_recording = False  # Reset the recording flag
                        print(f"Stopped recording video, total duration: {record_duration_seconds} seconds")

                # Reset the unsafe frame count for the next interval
                if self.total_frame_count % frame_interval == 0:
                    self.unsafe_frame_count = 0

            else:
                time.sleep(0.01)  # Increase sleep time slightly to reduce CPU usage

        # Release the video writer when stopping
        if out is not None:
            out.release()



    def stop(self):
        self.running = False
