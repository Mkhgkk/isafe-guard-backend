import cv2
import datetime
import threading
import time
import os
import logging
import numpy as np
import gi

import os
os.environ["GST_DEBUG"] = "3"

gi.require_version('Gst', '1.0')
from gi.repository import Gst
from bson import ObjectId
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
from utils.notifications import send_watch_notification, send_email_notification
from config import FRAME_HEIGHT, FRAME_WIDTH, RECONNECT_WAIT_TIME_IN_SECS, STATIC_DIR

RTMP_MEDIA_SERVER = os.getenv("RTMP_MEDIA_SERVER", "rtmp://localhost:1935")
NAMESPACE = "/default"

Gst.init(None)


def create_gstreamer_pipeline(rtsp_link):
    pipeline_str = (
        f"rtspsrc location={rtsp_link} latency=0 ! "
        f"decodebin ! videoconvert ! videoscale ! "
        f"video/x-raw, width={FRAME_WIDTH}, height={FRAME_HEIGHT}, format=BGR ! "
        f"appsink name=mysink drop=true"
    )

    return pipeline_str

# def create_gstreamer_pipeline(rtsp_link):
#     pipeline_str = (
#         f"rtspsrc location={rtsp_link} latency=0 protocols=4 ! "
#         f"decodebin ! videoconvert ! videoscale ! "
#         f"video/x-raw, width={FRAME_WIDTH}, height={FRAME_HEIGHT}, format=BGR ! "
#         f"appsink name=mysink drop=true"
#     )
#     return pipeline_str


# def create_gstreamer_pipeline(rtsp_link):
#     pipeline_str = (
#         f"rtspsrc location={rtsp_link} latency=0 ! queue ! "
#         f"decodebin ! queue ! videoconvert ! queue ! videoscale ! "
#         f"video/x-raw, width={FRAME_WIDTH}, height={FRAME_HEIGHT}, format=BGR ! "
#         f"queue ! appsink name=mysink drop=true max-buffers=1"
#     )
#     return pipeline_str


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
        self.pipeline = None

    def start_stream(self):
        self.running = True
        self.stop_event.clear()
        threading.Thread(target=self.generate_frames, daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, daemon=True).start()

    def stop_streaming(self):
        self.running = False
        self.stop_event.set()

    def generate_frames(self):
        pipeline_str = create_gstreamer_pipeline(self.rtsp_link)
        self.pipeline = Gst.parse_launch(pipeline_str)
        
        # Get the named appsink element
        appsink = self.pipeline.get_by_name("mysink")
        
        if not appsink:
            logging.error("Failed to get appsink element from GStreamer pipeline")
            return

        appsink.set_property("emit-signals", True)
        appsink.set_property("max-buffers", 1)
        appsink.set_property("drop", True)

        self.pipeline.set_state(Gst.State.PLAYING)
        logging.info(f"Started GStreamer pipeline for {self.rtsp_link}")

        while not self.stop_event.is_set():
            sample = appsink.emit("pull-sample")
            if sample:
                buffer = sample.get_buffer()
                caps = sample.get_caps()
                structure = caps.get_structure(0)
                width = structure.get_int("width")[1]
                height = structure.get_int("height")[1]

                success, map_info = buffer.map(Gst.MapFlags.READ)
                if success:
                    frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))
                    buffer.unmap(map_info)
                    
                    frame = frame.copy()

                    self.frame_buffer.put(frame)
                else:
                    logging.info("Failed to map buffer")

        self.pipeline.set_state(Gst.State.NULL)
        logging.info(f"Stopped GStreamer pipeline for {self.rtsp_link}")


    def process_and_emit_frames(self):
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
                processed_frame, final_status, reasons, person_bboxes = self.DETECTOR.detect(frame)
                transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
                processed_frame = self.safe_area_tracker.draw_safe_area_on_frame(processed_frame, transformed_hazard_zones)

                intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
                if intruders:
                    final_status = "Unsafe"
                    reasons.append("intrusion")
                    socketio.emit(f"alert-{self.stream_id}", {"type": "intrusion"}, namespace=NAMESPACE, room=self.stream_id)

                if final_status != "Safe":
                    self.unsafe_frame_count += 1

                self.total_frame_count += 1
                self.fps_queue.append(time.time())
                fps = 20.0 if len(self.fps_queue) <= 1 else len(self.fps_queue) / (self.fps_queue[-1] - self.fps_queue[0])
                draw_text_with_background(processed_frame, f"FPS: {int(fps)}", (1100, 20), (0, 0, 255), "fps")

                try:
                    if streamer_process.stdin:
                        streamer_process.stdin.write(processed_frame.tobytes())
                except BrokenPipeError:
                    streamer_process.stdin.close()
                    streamer_process.wait()
                    streamer_process = start_gstreamer_process(self.stream_id)

                if not is_recording and self.total_frame_count % frame_interval == 0:
                    unsafe_ratio = self.unsafe_frame_count / frame_interval if frame_interval else 0
                    if unsafe_ratio >= 0.7 and (time.time() - self.last_event_time) > self.event_cooldown_seconds:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        process, video_name = create_video_writer(self.stream_id, frame, timestamp, self.model_name, fps)
                        start_time = time.time()
                        is_recording = True
                        self.last_event_time = time.time()

                if is_recording and process:
                    try:
                        if process.stdin:
                            process.stdin.write(processed_frame.tobytes())
                    except BrokenPipeError:
                        is_recording = False
                        self.finalize_video(process)
                        process = None

                if is_recording and process and start_time and (time.time() - start_time) >= record_duration_seconds:
                    self.finalize_video(process)
                    process = None
                    start_time = None
                    is_recording = False

                if self.total_frame_count % frame_interval == 0:
                    self.unsafe_frame_count = 0
            else:
                time.sleep(0.01)

    def finalize_video(self, process):
        if process:
            process.stdin.close()
            process.wait()
