import cv2
import datetime
import threading
import time
import os
import logging
from collections import deque
from flask import current_app as app
from queue import Queue
from detection.detector import Detector
from socket_.socketio_instance import socketio
from intrusion import detect_intrusion
from intrusion.tracking import SafeAreaTracker
from main.shared import safe_area_trackers
from detection import draw_text_with_background
from main.event.model import Event
from utils import create_video_writer, start_gstreamer_process
from utils.notifications import send_watch_notification
from config import FRAME_HEIGHT, FRAME_WIDTH, RECONNECT_WAIT_TIME_IN_SECS, STATIC_DIR

RTMP_MEDIA_SERVER = os.getenv("RTMP_MEDIA_SERVER", "rtmp://localhost:1935")
NAMESPACE = "/default"


class StreamManager:
    def __init__(self, rtsp_link, model_name, stream_id, ptz_autotrack=False):
        self.DETECTOR = Detector(model_name)
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

        # self.EVENT_VIDEO_DIR = os.path.join(STATIC_DIR, self.stream_id, "videos")
        # self.EVENT_THUMBNAIL_DIR = os.path.join(STATIC_DIR, self.stream_id, "thumbnails")

    def start_stream(self):
        self.running = True
        self.stop_event.clear()
        threading.Thread(
            target=self.generate_frames,
            args=(self.rtsp_link, self.model_name),
            daemon=True,
        ).start()
        threading.Thread(
            target=self.process_and_emit_frames, args=(self.model_name,), daemon=True
        ).start()

    def stop_streaming(self):
        self.running = False
        self.stop_event.set()

    def generate_frames(self, rtsp_link, model_name):
        while not self.stop_event.is_set():

            video_capture = cv2.VideoCapture(rtsp_link)

            if not video_capture.isOpened():
                logging.info(
                    f"Unable to open video stream from {rtsp_link}. Retrying in 5 seconds..."
                )
                time.sleep(RECONNECT_WAIT_TIME_IN_SECS)
                continue

            fps = video_capture.get(cv2.CAP_PROP_FPS) or 20

            while not self.stop_event.is_set() and video_capture.isOpened():
                ret, frame = video_capture.read()

                if not ret:
                    logging.info(
                        f"Failed to read from {rtsp_link}. Attempting to reconnect..."
                    )
                    video_capture.release()
                    break

                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

                try:
                    self.frame_buffer.put_nowait(frame)
                except:
                    # logging.info("Frame buffer is full; dropping frame.")
                    pass

            video_capture.release()
            logging.info(
                f"Stream from {rtsp_link} disconnected. Reconnecting in 5 seconds..."
            )

            if not self.stop_event.is_set():
                time.sleep(RECONNECT_WAIT_TIME_IN_SECS)

    def process_and_emit_frames(self, model_name):
        process = None
        record_duration_seconds = 10
        frame_interval = 30
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        start_time = None
        is_recording = False

        streamer_process = start_gstreamer_process(self.stream_id)

        while not self.stop_event.is_set():
            if not self.frame_buffer.empty():
                frame = self.frame_buffer.get()
                transformed_hazard_zones = (
                    self.safe_area_tracker.get_transformed_safe_areas(frame)
                )
                processed_frame, final_status, reasons, person_bboxes = (
                    self.DETECTOR.detect(frame)
                )
                processed_frame = self.safe_area_tracker.draw_safe_area_on_frame(
                    processed_frame, transformed_hazard_zones
                )

                intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
                if len(intruders) > 0:
                    final_status = "Unsafe"
                    reasons.append("intrusion")
                    socketio.emit(
                        f"alert-{self.stream_id}",
                        {"type": "intrusion"},
                        namespace=NAMESPACE,
                        room=self.stream_id,  # type: ignore
                    )

                if self.ptz_autotrack and self.ptz_auto_tracker:
                    self.ptz_auto_tracker.track(
                        FRAME_WIDTH, FRAME_HEIGHT, person_bboxes
                    )

                if final_status != "Safe":
                    self.unsafe_frame_count += 1

                self.total_frame_count += 1
                self.fps_queue.append(time.time())
                if len(self.fps_queue) > 1:
                    time_diff = self.fps_queue[-1] - self.fps_queue[0]
                    fps = len(self.fps_queue) / time_diff if time_diff > 0 else 20.0
                else:
                    fps = 20.0
                draw_text_with_background(
                    processed_frame,
                    f"FPS: {int(fps)}",
                    (1100, 20),
                    (0, 0, 255),
                    "fps",
                )

                try:
                    if streamer_process.stdin is not None:
                        streamer_process.stdin.write(processed_frame.tobytes())
                except BrokenPipeError:
                    logging.info(
                        f"Streamer process for {self.stream_id} has stopped unexpectedly. Restarting..."
                    )
                    if streamer_process.stdin is not None:
                        streamer_process.stdin.close()
                        streamer_process.wait()
                        streamer_process = start_gstreamer_process(self.stream_id)

                if not is_recording and self.total_frame_count % frame_interval == 0:
                    unsafe_ratio = (
                        self.unsafe_frame_count / frame_interval
                        if frame_interval
                        else 0
                    )
                    if (
                        unsafe_ratio >= 0.7
                        and (time.time() - self.last_event_time)
                        > self.event_cooldown_seconds
                    ):
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        process, video_name = create_video_writer(
                            self.stream_id, frame, timestamp, model_name, fps
                        )
                        start_time = time.time()
                        is_recording = True
                        self.last_event_time = time.time()

                        save_thread = threading.Thread(
                            target=Event.save,
                            args=(
                                self.stream_id,
                                processed_frame,
                                list(set(reasons)),
                                self.model_name,
                                start_time,
                                video_name,
                            ),
                        )
                        notification_thread = threading.Thread(
                            target=send_watch_notification, args=(reasons)
                        )

                        save_thread.start()
                        logging.info(
                            f"Started recording unsafe event video for {self.stream_id}..."
                        )

                if is_recording and process is not None:
                    try:
                        if process.stdin is not None:
                            process.stdin.write(processed_frame.tobytes())
                    except BrokenPipeError:
                        logging.error(
                            f"Recording process for {self.stream_id} has stopped unexpectedly."
                        )
                        is_recording = False
                        self.finalize_video(process)
                        process = None

                if is_recording and process is not None and start_time is not None:
                    if (time.time() - start_time) >= record_duration_seconds:
                        self.finalize_video(process)

                        process = None
                        start_time = None
                        is_recording = False
                        logging.info(
                            f"Completed recording video for {self.stream_id}, total duration: {record_duration_seconds} seconds"
                        )

                if self.total_frame_count % frame_interval == 0:
                    self.unsafe_frame_count = 0

            else:
                time.sleep(0.01)

        if streamer_process:
            if streamer_process.stdin is not None:
                streamer_process.stdin.close()
                streamer_process.wait()

    def finalize_video(self, process):
        if process:
            process.stdin.close()
            process.wait()
