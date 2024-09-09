import cv2
import datetime
import threading
import time
import asyncio
from collections import deque
from multiprocessing import Process, Queue
from detection.object_detection import ObjectDetection
from utils.camera_controller import CameraController
from socketio_instance import socketio

class VideoStreaming:
    def __init__(self, rtsp_link, model_name, stream_id, ptz_autotrack=False):
        self.MODEL = ObjectDetection()
        self.fps_queue = deque(maxlen=30)
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        self.frames_written = 0
        self.video_name = None

        self.frame_queue = Queue(maxsize=10)
        self.result_queue = Queue(maxsize=10)
        self.running = False

        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        self.ptz_autotrack = ptz_autotrack

    def process_video(self, frame, model_name, out, video_count):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if self._detect:
            if out is None:
                fps = self.VIDEO.get(cv2.CAP_PROP_FPS) or 20
                out, self.video_name = self.create_video_writer(frame, timestamp, model_name, fps)
            frame, timestamp, final_status, inference_time = self.MODEL.detectObj(frame, timestamp, model_name)
            self.total_frame_count += 1
            if final_status == "UnSafe" and out is not None:
                out.write(frame)
                self.unsafe_frame_count += 1
                self.frames_written += 1

        return frame, out, self.total_frame_count, timestamp, self.video_name

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
        video_name1 = f"./static/unsafe/video_{model_name}_{timestamp}.mp4"
        video_name = f"/unsafe/video_{model_name}_{timestamp}.mp4"
        height, width, _ = frame.shape
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        return cv2.VideoWriter(video_name1, fourcc, output_fps, (width, height)), video_name

    def start_stream(self):
        self.running = True

        # Start the multiprocessing processes
        generate_process = Process(target=self.generate_frames, args=(self.rtsp_link, self.frame_queue))
        process_process = Process(target=self.process_frames, args=(self.frame_queue, self.result_queue, self.model_name))

        generate_process.start()
        process_process.start()

        # Start the thread for emitting frames via socketio
        threading.Thread(target=self.emit_frames, daemon=True).start()

    def stop_streaming(self):
        self.running = False

    def generate_frames(self, rtsp_link, frame_queue):
        video_capture = cv2.VideoCapture(rtsp_link)
        if not video_capture.isOpened():
            print(f"Error: Unable to open video stream from {rtsp_link}")
            return

        fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
        desired_width, desired_height = 1280, 720

        while self.running and video_capture.isOpened():
            ret, frame = video_capture.read()
            if not ret:
                print(f"Failed to read from {rtsp_link}")
                break

            frame = cv2.resize(frame, (desired_width, desired_height))

            try:
                frame_queue.put_nowait(frame)
            except:
                print("Frame buffer is full; dropping frame.")

        video_capture.release()

    def process_frames(self, frame_queue, result_queue, model_name):
        while self.running:
            if not frame_queue.empty():
                frame = frame_queue.get()
                processed_frame, final_status = self.apply_model(frame, model_name)
                result_queue.put((processed_frame, final_status))
            else:
                time.sleep(0.01)

    def emit_frames(self):
        while self.running:
            if not self.result_queue.empty():
                frame, final_status = self.result_queue.get()
                ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 20])
                frame_data = buffer.tobytes()

                # Emit the frame via socketio in the main process
                socketio.emit(f'frame-{self.stream_id}', {'image': frame_data}, namespace='/video', room=self.stream_id)
            else:
                time.sleep(0.01)

    def stop(self):
        self.running = False
