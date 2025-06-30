import os
import gi

os.environ["GST_DEBUG"] = "1"
gi.require_version('Gst', '1.0')

import cv2
import datetime
import threading
import time
import logging
import numpy as np

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
from detection import draw_text_with_background, draw_status_info
from main.event.model import Event
from utils import create_video_writer, start_gstreamer_process
from utils.notifications import send_watch_notification, send_email_notification
from config import FRAME_HEIGHT, FRAME_WIDTH, RECONNECT_WAIT_TIME_IN_SECS, STATIC_DIR


RTMP_MEDIA_SERVER = os.getenv("RTMP_MEDIA_SERVER", "rtmp://localhost:1935")
NAMESPACE = "/default"

Gst.init(None)


def create_gstreamer_pipeline(rtsp_link, sink_name):
    """
    Creates a more robust GStreamer pipeline for RTSP sources.
    Uses TCP to avoid firewall and UDP buffer size issues.
    
    Args:
        rtsp_link: RTSP URL to connect to
        sink_name: Unique name for the appsink element
        
    Returns:
        GStreamer pipeline string
    """
    # Primary pipeline - Explicitly force TCP transport
    pipeline_str = (
        f"rtspsrc location={rtsp_link} latency=0 "
        f"protocols=tcp "  # Force TCP protocol
        f"buffer-mode=auto drop-on-latency=true retry=3 timeout=5 "
        f"! application/x-rtp, media=video "  # Only process video streams
        f"! rtpjitterbuffer latency=200 "
        # f"! rtph264depay "
        # f"! h264parse "
        f"! decodebin "
        f"! videoconvert "
        f"! videoscale "
        f"! video/x-raw, width={FRAME_WIDTH}, height={FRAME_HEIGHT}, format=BGR "
        f"! appsink name={sink_name} drop=true max-buffers=2 emit-signals=true sync=false"
    )
    
    return pipeline_str

def create_alternative_pipeline(rtsp_link, sink_name):
    """
    Alternative pipeline that's more flexible but still uses TCP.
    
    Args:
        rtsp_link: RTSP URL to connect to
        sink_name: Unique name for the appsink element
        
    Returns:
        Alternative GStreamer pipeline string
    """
    # Simplified alternative pipeline
    alt_pipeline_str = (
        f"rtspsrc location={rtsp_link} latency=0 "
        f"protocols=tcp "  # Force TCP protocol
        f"retry=3 timeout=10 "
        f"! decodebin "
        f"! videoconvert "
        f"! videoscale "
        f"! video/x-raw, width={FRAME_WIDTH}, height={FRAME_HEIGHT}, format=BGR "
        f"! appsink name={sink_name} drop=true max-buffers=2 emit-signals=true sync=false"
    )
    
    return alt_pipeline_str



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
        self.max_reconnect_attempts = 10
        self.reconnect_delay = RECONNECT_WAIT_TIME_IN_SECS
        self.last_frame_time = 0
        self.frame_timeout = 5  # Consider connection lost if no frames for 5 seconds
        self.sink_name = f"sink_{stream_id}"  # Unique sink name for each stream

        self.use_alternative_pipeline = False  # Try alternative pipeline as fallback
        self.connection_trials = 0  # Track connection attempts

    def start_stream(self):
        self.running = True
        self.stop_event.clear()
        threading.Thread(target=self.generate_frames, daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, daemon=True).start()
        threading.Thread(target=self.monitor_stream_health, daemon=True).start()

    def stop_streaming(self):
        self.running = False
        self.stop_event.set()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

    def monitor_stream_health(self):
        """Monitor the stream health and trigger reconnection if needed."""
        while not self.stop_event.is_set():
            time.sleep(1)
            if self.running and time.time() - self.last_frame_time > self.frame_timeout and self.last_frame_time > 0:
                logging.warning(f"No frames received for {self.frame_timeout} seconds. "
                              f"Reconnecting stream {self.stream_id}...")
                self.restart_pipeline()
                

    def create_and_start_pipeline(self):
        """Create and start a new GStreamer pipeline with TCP transport."""
        pipeline_str = create_gstreamer_pipeline(self.rtsp_link, self.sink_name)
        
        # Try alternative pipeline if we've had multiple failures
        if self.use_alternative_pipeline:
            logging.info(f"Using alternative pipeline for {self.stream_id}")
            pipeline_str = create_alternative_pipeline(self.rtsp_link, self.sink_name)
        
        # For debugging - log the full pipeline string
        logging.info(f"Creating pipeline: {pipeline_str}")
        
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
            
            # Get the named appsink element
            appsink = self.pipeline.get_by_name(self.sink_name)
            
            if not appsink:
                logging.error(f"Failed to get appsink element '{self.sink_name}' from GStreamer pipeline")
                return False

            # Connect to bus messages to handle errors
            bus = self.pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self.on_bus_message)

            appsink.set_property("emit-signals", True)
            appsink.set_property("max-buffers", 2)
            appsink.set_property("drop", True)
            appsink.set_property("sync", False)  # Don't sync to clock for better performance
            
            # Set up callback for new-sample signal
            appsink.connect("new-sample", self.on_new_sample)

            # Start the pipeline
            logging.info(f"Setting pipeline state to PLAYING for stream {self.stream_id}")
            ret = self.pipeline.set_state(Gst.State.PLAYING)
            
            # Check pipeline state change result
            if ret == Gst.StateChangeReturn.FAILURE:
                logging.error(f"Failed to start pipeline for stream {self.stream_id}")
                return False
            elif ret == Gst.StateChangeReturn.ASYNC:
                # State change will happen asynchronously, wait for it
                logging.info(f"Pipeline state change async for {self.stream_id}, waiting...")
                ret = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)  # Wait indefinitely
                logging.info(f"Pipeline state change result: {ret[0]}")
                if ret[0] != Gst.StateChangeReturn.SUCCESS:
                    logging.error(f"Pipeline state change failed for stream {self.stream_id}")
                    return False
                
            logging.info(f"Successfully started GStreamer pipeline for {self.rtsp_link}")
            self.connection_trials = 0  # Reset connection trials on success
            self.last_frame_time = time.time()  # Initialize frame time to avoid immediate reconnect
            return True
        except Exception as e:
            logging.error(f"Error creating pipeline: {e}")
            self.connection_trials += 1
            
            # Try alternative pipeline after several failures
            if self.connection_trials >= 2 and not self.use_alternative_pipeline:
                self.use_alternative_pipeline = True
                logging.info("Switching to alternative pipeline on next attempt")
                
            return False

    def on_new_sample(self, appsink):
        """Callback for new-sample signal from appsink."""
        try:
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
                    self.last_frame_time = time.time()
                    
                    # Don't block if the queue is full
                    if not self.frame_buffer.full():
                        self.frame_buffer.put(frame)
                else:
                    logging.warning("Failed to map buffer")
            return Gst.FlowReturn.OK
        except Exception as e:
            logging.error(f"Error in on_new_sample: {e}")
            return Gst.FlowReturn.ERROR


    def on_bus_message(self, bus, message):
        """Enhanced handler for GStreamer bus messages."""
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logging.error(f"GStreamer error: {err.message}, {debug}")
            
            # Check if error is related to ONVIF metadata
            if "Missing decoder: application/x-rtp" in str(err.message) and "ONVIF.METADATA" in str(debug):
                logging.warning("ONVIF metadata handling issue detected, will use filtered pipeline on reconnect")
                self.use_alternative_pipeline = True
            
            # More detailed handling of common RTSP errors
            if any(x in str(err.message) or x in str(debug) for x in 
                   ["Timeout", "connection refused", "404", "554", "503", "401", 
                    "not-linked", "Internal data stream error", "Could not connect", 
                    "Could not receive", "buffer underflow", "Internal data flow error",
                    "blocking", "firewall", "property does not exist", "your firewall",
                    "UDP packets"]):
                logging.warning(f"RTSP connection error for stream {self.stream_id}. Will attempt to reconnect.")
                self.restart_pipeline()
        
        elif t == Gst.MessageType.EOS:
            logging.warning(f"End of stream received for {self.stream_id}. Will attempt to reconnect.")
            self.restart_pipeline()
            
        elif t == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            logging.warning(f"GStreamer warning: {warn.message}, {debug}")
            
            # Check for UDP and firewall related warnings
            if "UDP" in str(warn.message) or "firewall" in str(warn.message) or "tcp" in str(warn.message):
                logging.warning("Network-related warning detected, may need to reconnect soon")
                
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                state_names = {
                    Gst.State.NULL: "NULL",
                    Gst.State.READY: "READY",
                    Gst.State.PAUSED: "PAUSED",
                    Gst.State.PLAYING: "PLAYING"
                }
                old_name = state_names.get(old_state, str(old_state))
                new_name = state_names.get(new_state, str(new_state))
                logging.info(f"Pipeline state for {self.stream_id} changed from {old_name} to {new_name}")
                
                if new_state == Gst.State.PLAYING:
                    # Reset frame timeout monitor since we're just starting
                    self.last_frame_time = time.time()
                elif new_state == Gst.State.PAUSED and old_state == Gst.State.PLAYING:
                    logging.warning(f"Pipeline for stream {self.stream_id} paused unexpectedly")
                    # This might indicate network issues
                    self.restart_pipeline()

    def restart_pipeline(self):
        """Safely restart the GStreamer pipeline."""
        logging.info(f"Restarting pipeline for stream {self.stream_id}")
        
        if self.pipeline:
            # Get current state before stopping
            state_result = self.pipeline.get_state(0)
            current_state = state_result[1]
            logging.info(f"Current pipeline state before restart: {current_state}")
            
            # Set to NULL state to clean up resources
            ret = self.pipeline.set_state(Gst.State.NULL)
            if ret == Gst.StateChangeReturn.ASYNC:
                # Wait for state change to complete
                self.pipeline.get_state(3 * Gst.SECOND)
            
            self.pipeline = None
            
        # Wait before reconnecting to avoid rapid reconnection attempts
        time.sleep(self.reconnect_delay)
        
        # Attempt to create and start a new pipeline
        return self.create_and_start_pipeline()


    def generate_frames(self):
        """Main method to capture frames from the RTSP stream using GStreamer."""
        reconnect_attempt = 0
        
        while not self.stop_event.is_set():
            if not self.pipeline and not self.create_and_start_pipeline():
                reconnect_attempt += 1
                wait_time = min(self.reconnect_delay * min(reconnect_attempt, 5), 60)  # Cap at 60 seconds
                logging.warning(f"Reconnection attempt {reconnect_attempt} failed. "
                              f"Will retry in {wait_time} seconds")
                
                time.sleep(wait_time)
                continue
            else:
                reconnect_attempt = 0  # Reset counter on successful connection
            
            # Main loop just waits for frames via callbacks
            while not self.stop_event.is_set():
                # Check if we need to restart the pipeline
                if not self.pipeline:
                    break
                
                # Sleep to avoid busy waiting
                time.sleep(0.1)
                
                # If no frames for a while, check pipeline health
                current_time = time.time()
                if self.last_frame_time > 0 and current_time - self.last_frame_time > 10:
                    # Query pipeline state to see if it's still PLAYING
                    state_result = self.pipeline.get_state(0)
                    if state_result[1] != Gst.State.PLAYING:
                        logging.warning(f"Pipeline for {self.stream_id} not in PLAYING state. Current state: {state_result[1]}. Restarting.")
                        self.restart_pipeline()
                        break
                    else:
                        logging.warning(f"No frames received for {current_time - self.last_frame_time} seconds despite PLAYING state. May need to restart.")
                        # If it's been too long since last frame (30 seconds), force restart anyway
                        if current_time - self.last_frame_time > 30:
                            logging.warning(f"Forcing pipeline restart after 30 seconds with no frames for {self.stream_id}")
                            self.restart_pipeline()
                            break


    def process_and_emit_frames(self):
        process = None
        record_duration_seconds = 10
        frame_interval = 30
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        start_time = None
        is_recording = False
        video_name = None
        streamer_process = start_gstreamer_process(self.stream_id)

        while not self.stop_event.is_set():
            try:
                if not self.frame_buffer.empty():
                    frame = self.frame_buffer.get(timeout=0.5)
                    processed_frame, final_status, reasons, person_bboxes = self.DETECTOR.detect(frame)
                    transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
                    processed_frame = self.safe_area_tracker.draw_safe_area_on_frame(processed_frame, transformed_hazard_zones)

                    intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
                    if intruders:
                        final_status = "Unsafe"
                        reasons.append("intrusion")
                        socketio.emit(f"alert-{self.stream_id}", {"type": "intrusion"}, namespace=NAMESPACE, room=self.stream_id)

                    # PTZ auto tracking if enabled
                    if hasattr(self, 'ptz_autotrack') and self.ptz_autotrack and hasattr(self, 'ptz_auto_tracker') and self.ptz_auto_tracker:
                        self.ptz_auto_tracker.track(FRAME_WIDTH, FRAME_HEIGHT, person_bboxes)

                    if final_status != "Safe":
                        self.unsafe_frame_count += 1

                    self.total_frame_count += 1
                    self.fps_queue.append(time.time())
                    fps = 20.0 if len(self.fps_queue) <= 1 else len(self.fps_queue) / (self.fps_queue[-1] - self.fps_queue[0])
                    # draw_text_with_background(processed_frame, f"FPS: {int(fps)}", (1100, 20), (0, 0, 255), "fps")

                    draw_status_info(processed_frame, reasons, fps)

                    try:
                        if streamer_process and streamer_process.stdin:
                            streamer_process.stdin.write(processed_frame.tobytes())
                    except BrokenPipeError:
                        if streamer_process:
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
                            
                            # Create Event ID and save event
                            _event_id = ObjectId()
                            
                            # Start threads for event saving and notifications
                            save_thread = threading.Thread(
                                target=Event.save,
                                args=(
                                    self.stream_id,
                                    processed_frame,
                                    list(set(reasons)),
                                    self.model_name,
                                    start_time,
                                    video_name,
                                    _event_id,
                                ),
                            )
                            
                            email_notification_thread = threading.Thread(
                                target=send_email_notification,
                                args=(reasons, _event_id, self.stream_id),
                            )
                            
                            watch_notification_thread = threading.Thread(
                                target=send_watch_notification, 
                                args=(reasons,)  # Note: Added comma to make it a tuple
                            )
                            
                            # Start the threads
                            save_thread.start()
                            email_notification_thread.start()
                            # Uncomment if you want to enable watch notifications
                            # watch_notification_thread.start()
                            
                            logging.info(f"Started recording unsafe event video for {self.stream_id}...")

                    if is_recording and process:
                        try:
                            if process.stdin:
                                process.stdin.write(processed_frame.tobytes())
                        except BrokenPipeError:
                            logging.error(f"Recording process for {self.stream_id} has stopped unexpectedly.")
                            is_recording = False
                            self.finalize_video(process)
                            process = None

                    if is_recording and process and start_time and (time.time() - start_time) >= record_duration_seconds:
                        self.finalize_video(process)
                        process = None
                        start_time = None
                        is_recording = False
                        logging.info(f"Completed recording video for {self.stream_id}, total duration: {record_duration_seconds} seconds")

                    if self.total_frame_count % frame_interval == 0:
                        self.unsafe_frame_count = 0
                else:
                    time.sleep(0.01)
            except Exception as e:
                logging.error(f"Error in processing frame: {e}")
                time.sleep(0.1)  # Avoid tight loop on errors

        # Clean up the streamer process when stopping
        if streamer_process:
            if streamer_process.stdin:
                streamer_process.stdin.close()
                streamer_process.wait()

    def finalize_video(self, process):
        if process:
            process.stdin.close()
            process.wait()