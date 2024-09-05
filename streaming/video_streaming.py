import cv2
import datetime
import threading
import time
import asyncio
from collections import deque
from queue import Queue
from detection.object_detection import ObjectDetection
from utils.camera_controller import CameraController
from socketio_instance import socketio

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

    @property
    def preview(self):
        return self._preview

    @preview.setter
    def preview(self, value):
        self._preview = bool(value)

    @property
    def flipH(self):
        return self._flipH

    @flipH.setter
    def flipH(self, value):
        self._flipH = bool(value)

    @property
    def detect(self):
        return self._detect

    @detect.setter
    def detect(self, value):
        self._detect = bool(value)

    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, value):
        self._exposure = value
        self.VIDEO.set(cv2.CAP_PROP_EXPOSURE, self._exposure)

    @property
    def contrast(self):
        return self._contrast

    @contrast.setter
    def contrast(self, value):
        self._contrast = value
        self.VIDEO.set(cv2.CAP_PROP_CONTRAST, self._contrast)

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
        video_name1 = f"./static/unsafe/video_{model_name}_{timestamp}.mp4"
        video_name = f"/unsafe/video_{model_name}_{timestamp}.mp4"
        height, width, _ = frame.shape
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        return cv2.VideoWriter(video_name1, fourcc, output_fps, (width, height)), video_name

    def start_stream(self):
        self.running = True
        threading.Thread(target=self.generate_frames, args=(self.rtsp_link, self.model_name), daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, args=(self.model_name,), daemon=True).start()

    def stop_streaming(self):
        self.running = False

    def generate_frames(self, rtsp_link, model_name):
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
                self.frame_buffer.put_nowait(frame)
            except:
                print("Frame buffer is full; dropping frame.")

        video_capture.release()

    def process_and_emit_frames(self, model_name):
        while self.running:
            if not self.frame_buffer.empty():
                frame = self.frame_buffer.get()
                processed_frame, final_status = self.apply_model(frame, model_name)

                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 30])
                frame_data = buffer.tobytes()

                socketio.emit(f'frame-{self.stream_id}', {'image': frame_data}, namespace='/video', room=self.stream_id)
            else:
                time.sleep(0.01)

    def stop(self):
        self.running = False
