import os
import gi
import cv2
import datetime
import threading
import time
import logging
import numpy as np
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

os.environ["GST_DEBUG"] = "1"
gi.require_version('Gst', '1.0')

from gi.repository import Gst
from bson import ObjectId
from collections import deque
from flask import current_app as app
from queue import Queue, Empty
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

# Constants
RTMP_MEDIA_SERVER = os.getenv("RTMP_MEDIA_SERVER", "rtmp://localhost:1935")
NAMESPACE = "/default"
DEFAULT_FRAME_TIMEOUT = 5
DEFAULT_RECORD_DURATION = 10
DEFAULT_FRAME_INTERVAL = 30
DEFAULT_UNSAFE_RATIO_THRESHOLD = 0.7
DEFAULT_EVENT_COOLDOWN = 30
MAX_RECONNECT_WAIT = 60
MAX_BUFFER_SIZE = 2
MAX_FRAME_QUEUE_SIZE = 10
FPS_QUEUE_SIZE = 30

Gst.init(None)


class ConnectionState(Enum):
    """Enum for connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class PipelineConfig:
    """Configuration for GStreamer pipeline."""
    rtsp_link: str
    sink_name: str
    width: int = FRAME_WIDTH
    height: int = FRAME_HEIGHT
    format: str = "BGR"
    latency: int = 0
    max_buffers: int = MAX_BUFFER_SIZE
    timeout: int = 5
    retry_count: int = 3


@dataclass
class RecordingState:
    """State tracking for video recording."""
    is_recording: bool = False
    process: Optional[Any] = None
    start_time: Optional[float] = None
    video_name: Optional[str] = None
    duration_seconds: int = DEFAULT_RECORD_DURATION


@dataclass
class StreamStats:
    """Statistics for stream processing."""
    total_frames: int = 0
    unsafe_frames: int = 0
    fps_queue: deque = None
    last_event_time: float = 0
    
    def __post_init__(self):
        if self.fps_queue is None:
            self.fps_queue = deque(maxlen=FPS_QUEUE_SIZE)


class PipelineBuilder:
    """Builder class for creating GStreamer pipelines."""
    
    @staticmethod
    def create_primary_pipeline(config: PipelineConfig) -> str:
        """Create the primary GStreamer pipeline with TCP transport."""
        return (
            f"rtspsrc location={config.rtsp_link} latency={config.latency} "
            f"protocols=tcp "
            f"buffer-mode=auto drop-on-latency=true retry={config.retry_count} timeout={config.timeout} "
            f"! application/x-rtp, media=video "
            f"! rtpjitterbuffer latency=200 "
            f"! decodebin "
            f"! videoconvert "
            f"! videoscale "
            f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
            f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
            f"emit-signals=true sync=false"
        )
    
    @staticmethod
    def create_alternative_pipeline(config: PipelineConfig) -> str:
        """Create an alternative, more flexible pipeline."""
        return (
            f"rtspsrc location={config.rtsp_link} latency={config.latency} "
            f"protocols=tcp "
            f"retry={config.retry_count} timeout=10 "
            f"! decodebin "
            f"! videoconvert "
            f"! videoscale "
            f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
            f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
            f"emit-signals=true sync=false"
        )


class GStreamerPipeline:
    """Wrapper class for GStreamer pipeline management."""
    
    def __init__(self, config: PipelineConfig, stream_id: str):
        self.config = config
        self.stream_id = stream_id
        self.pipeline: Optional[Gst.Pipeline] = None
        self.use_alternative = False
        self.connection_trials = 0
        self.last_frame_time = 0
        self.frame_callback = None
        
    def create_and_start(self, frame_callback) -> bool:
        """Create and start the GStreamer pipeline."""
        self.frame_callback = frame_callback
        
        # Choose pipeline type based on previous failures
        if self.use_alternative:
            pipeline_str = PipelineBuilder.create_alternative_pipeline(self.config)
            logging.info(f"Using alternative pipeline for {self.stream_id}")
        else:
            pipeline_str = PipelineBuilder.create_primary_pipeline(self.config)
            
        logging.info(f"Creating pipeline: {pipeline_str}")
        
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
            return self._configure_pipeline()
        except Exception as e:
            logging.error(f"Error creating pipeline: {e}")
            self.connection_trials += 1
            
            # Switch to alternative after multiple failures
            if self.connection_trials >= 2 and not self.use_alternative:
                self.use_alternative = True
                logging.info("Switching to alternative pipeline on next attempt")
                
            return False
    
    def _configure_pipeline(self) -> bool:
        """Configure the pipeline elements and start it."""
        appsink = self.pipeline.get_by_name(self.config.sink_name)
        if not appsink:
            logging.error(f"Failed to get appsink element '{self.config.sink_name}'")
            return False
            
        # Configure appsink
        appsink.set_property("emit-signals", True)
        appsink.set_property("max-buffers", self.config.max_buffers)
        appsink.set_property("drop", True)
        appsink.set_property("sync", False)
        appsink.connect("new-sample", self._on_new_sample)
        
        # Connect bus messages
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        
        # Start pipeline
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logging.error(f"Failed to start pipeline for stream {self.stream_id}")
            return False
            
        if ret == Gst.StateChangeReturn.ASYNC:
            ret = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
            if ret[0] != Gst.StateChangeReturn.SUCCESS:
                logging.error(f"Pipeline state change failed for stream {self.stream_id}")
                return False
                
        logging.info(f"Successfully started GStreamer pipeline for {self.stream_id}")
        self.connection_trials = 0
        self.last_frame_time = time.time()
        return True
    
    def _on_new_sample(self, appsink) -> Gst.FlowReturn:
        """Handle new sample from appsink."""
        try:
            sample = appsink.emit("pull-sample")
            if not sample:
                return Gst.FlowReturn.OK
                
            frame = self._extract_frame_from_sample(sample)
            if frame is not None:
                self.last_frame_time = time.time()
                if self.frame_callback:
                    self.frame_callback(frame)
                    
            return Gst.FlowReturn.OK
        except Exception as e:
            logging.error(f"Error in _on_new_sample: {e}")
            return Gst.FlowReturn.ERROR
    
    def _extract_frame_from_sample(self, sample) -> Optional[np.ndarray]:
        """Extract numpy frame from GStreamer sample."""
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_int("width")[1]
        height = structure.get_int("height")[1]
        
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if not success:
            logging.warning("Failed to map buffer")
            return None
            
        try:
            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3))
            return frame.copy()
        finally:
            buffer.unmap(map_info)
    
    def _on_bus_message(self, bus, message):
        """Handle GStreamer bus messages."""
        msg_type = message.type
        
        if msg_type == Gst.MessageType.ERROR:
            self._handle_error_message(message)
        elif msg_type == Gst.MessageType.EOS:
            logging.warning(f"End of stream for {self.stream_id}")
        elif msg_type == Gst.MessageType.WARNING:
            self._handle_warning_message(message)
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            self._handle_state_change_message(message)
    
    def _handle_error_message(self, message):
        """Handle error messages from GStreamer."""
        err, debug = message.parse_error()
        logging.error(f"GStreamer error: {err.message}, {debug}")
        
        # Check for ONVIF metadata issues
        if "ONVIF.METADATA" in str(debug):
            logging.warning("ONVIF metadata issue detected")
            self.use_alternative = True
    
    def _handle_warning_message(self, message):
        """Handle warning messages from GStreamer."""
        warn, debug = message.parse_warning()
        logging.warning(f"GStreamer warning: {warn.message}, {debug}")
    
    def _handle_state_change_message(self, message):
        """Handle state change messages."""
        if message.src != self.pipeline:
            return
            
        old_state, new_state, _ = message.parse_state_changed()
        state_names = {
            Gst.State.NULL: "NULL",
            Gst.State.READY: "READY", 
            Gst.State.PAUSED: "PAUSED",
            Gst.State.PLAYING: "PLAYING"
        }
        
        old_name = state_names.get(old_state, str(old_state))
        new_name = state_names.get(new_state, str(new_state))
        logging.info(f"Pipeline state for {self.stream_id}: {old_name} -> {new_name}")
        
        if new_state == Gst.State.PLAYING:
            self.last_frame_time = time.time()
    
    def stop(self):
        """Stop the pipeline."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
    
    def is_healthy(self) -> bool:
        """Check if pipeline is healthy."""
        if not self.pipeline:
            return False
            
        current_time = time.time()
        if self.last_frame_time > 0 and current_time - self.last_frame_time > DEFAULT_FRAME_TIMEOUT:
            return False
            
        return True


class EventProcessor:
    """Handles event processing and recording logic."""
    
    def __init__(self, stream_id: str, model_name: str):
        self.stream_id = stream_id
        self.model_name = model_name
        self.recording_state = RecordingState()
        
    def should_start_recording(self, unsafe_ratio: float, last_event_time: float) -> bool:
        """Determine if recording should start based on unsafe ratio and cooldown."""
        cooldown_elapsed = (time.time() - last_event_time) > DEFAULT_EVENT_COOLDOWN
        return unsafe_ratio >= DEFAULT_UNSAFE_RATIO_THRESHOLD and cooldown_elapsed
    
    def start_recording(self, frame: np.ndarray, reasons: List[str], fps: float) -> str:
        """Start video recording for an event."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        process, video_name = create_video_writer(
            self.stream_id, frame, timestamp, self.model_name, fps
        )
        
        self.recording_state.is_recording = True
        self.recording_state.process = process
        self.recording_state.start_time = time.time()
        self.recording_state.video_name = video_name
        
        # Start event processing threads
        self._start_event_threads(frame, reasons, video_name)
        
        logging.info(f"Started recording for {self.stream_id}")
        return video_name
    
    def _start_event_threads(self, frame: np.ndarray, reasons: List[str], video_name: str):
        """Start threads for event saving and notifications."""
        event_id = ObjectId()
        
        threads = [
            threading.Thread(
                target=Event.save,
                args=(
                    self.stream_id, frame, list(set(reasons)), 
                    self.model_name, self.recording_state.start_time, 
                    video_name, event_id
                )
            ),
            threading.Thread(
                target=send_email_notification,
                args=(reasons, event_id, self.stream_id)
            ),
            threading.Thread(
                target=send_watch_notification,
                args=(reasons,)
            )
        ]
        
        for thread in threads:
            thread.start()
    
    def write_frame(self, frame: np.ndarray) -> bool:
        """Write frame to recording process."""
        if not self.recording_state.is_recording or not self.recording_state.process:
            return False
            
        try:
            if self.recording_state.process.stdin:
                self.recording_state.process.stdin.write(frame.tobytes())
                return True
        except BrokenPipeError:
            logging.error(f"Recording process for {self.stream_id} stopped unexpectedly")
            self.stop_recording()
            
        return False
    
    def should_stop_recording(self) -> bool:
        """Check if recording should stop based on duration."""
        if not self.recording_state.is_recording or not self.recording_state.start_time:
            return False
            
        elapsed = time.time() - self.recording_state.start_time
        return elapsed >= self.recording_state.duration_seconds
    
    def stop_recording(self):
        """Stop video recording."""
        if self.recording_state.process:
            try:
                self.recording_state.process.stdin.close()
                self.recording_state.process.wait()
            except Exception as e:
                logging.error(f"Error stopping recording: {e}")
                
        self.recording_state.is_recording = False
        self.recording_state.process = None
        self.recording_state.start_time = None
        
        logging.info(f"Stopped recording for {self.stream_id}")


class StreamManager:
    """Main class for managing RTSP stream processing."""
    
    def __init__(self, rtsp_link: str, model_name: str, stream_id: str, ptz_autotrack: bool = False):
        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        self.ptz_autotrack = ptz_autotrack
        
        # Initialize components
        self.detector = Detector(model_name)
        self.safe_area_tracker = SafeAreaTracker()
        self.event_processor = EventProcessor(stream_id, model_name)
        self.stats = StreamStats()
        
        # Threading and state management
        self.frame_buffer = Queue(maxsize=MAX_FRAME_QUEUE_SIZE)
        self.running = False
        self.stop_event = threading.Event()
        
        # Pipeline configuration
        pipeline_config = PipelineConfig(
            rtsp_link=rtsp_link,
            sink_name=f"sink_{stream_id}"
        )
        self.pipeline = GStreamerPipeline(pipeline_config, stream_id)
        
        # Register safe area tracker
        safe_area_trackers[stream_id] = self.safe_area_tracker

        # Camera controller
        self.camera_controller = None
        
        # PTZ tracking setup
        self.ptz_auto_tracker = None
        if ptz_autotrack:
            # Initialize PTZ tracker here if needed
            pass
    
    def start_stream(self):
        """Start the stream processing."""
        self.running = True
        self.stop_event.clear()
        
        threads = [
            threading.Thread(target=self._frame_capture_loop, daemon=True),
            threading.Thread(target=self._frame_processing_loop, daemon=True),
            threading.Thread(target=self._health_monitor_loop, daemon=True)
        ]
        
        for thread in threads:
            thread.start()
    
    def stop_streaming(self):
        """Stop the stream processing."""
        self.running = False
        self.stop_event.set()
        self.pipeline.stop()
    
    def _frame_capture_loop(self):
        """Main loop for capturing frames from RTSP stream."""
        reconnect_attempt = 0
        
        while not self.stop_event.is_set():
            if not self.pipeline.pipeline:
                if not self.pipeline.create_and_start(self._on_frame_received):
                    reconnect_attempt += 1
                    wait_time = min(RECONNECT_WAIT_TIME_IN_SECS * min(reconnect_attempt, 5), MAX_RECONNECT_WAIT)
                    logging.warning(f"Reconnection attempt {reconnect_attempt} failed. Retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                else:
                    reconnect_attempt = 0
            
            # Main capture loop
            while not self.stop_event.is_set() and self.pipeline.pipeline:
                time.sleep(0.1)
                
                # Check pipeline health
                if not self.pipeline.is_healthy():
                    logging.warning(f"Pipeline unhealthy for {self.stream_id}, restarting")
                    self.pipeline.stop()
                    break
    
    def _on_frame_received(self, frame: np.ndarray):
        """Callback for when a new frame is received."""
        if not self.frame_buffer.full():
            self.frame_buffer.put(frame)
    
    def _frame_processing_loop(self):
        """Main loop for processing frames."""
        streamer_process = start_gstreamer_process(self.stream_id)
        
        while not self.stop_event.is_set():
            try:
                frame = self.frame_buffer.get(timeout=0.5)
                processed_frame = self._process_frame(frame)
                
                # Stream processed frame
                self._stream_frame(streamer_process, processed_frame)
                
                # Handle recording
                self._handle_recording(processed_frame)
                
            except Empty:
                continue
            except Exception as e:
                logging.error(f"Error in frame processing: {e}")
                time.sleep(0.1)
        
        # Cleanup
        if streamer_process:
            streamer_process.stdin.close()
            streamer_process.wait()
    
    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Process a single frame through detection and tracking."""
        # Run detection
        processed_frame, final_status, reasons, person_bboxes = self.detector.detect(frame)
        
        # Handle safe areas
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
        processed_frame = self.safe_area_tracker.draw_safe_area_on_frame(
            processed_frame, transformed_hazard_zones
        )
        
        # Check for intrusions
        intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
        if intruders:
            final_status = "Unsafe"
            reasons.append("intrusion")
            socketio.emit(
                f"alert-{self.stream_id}", 
                {"type": "intrusion"}, 
                namespace=NAMESPACE, 
                room=self.stream_id
            )
        
        # PTZ tracking
        if self.ptz_autotrack and self.ptz_auto_tracker:
            self.ptz_auto_tracker.track(FRAME_WIDTH, FRAME_HEIGHT, person_bboxes)
        
        # Update statistics
        self._update_stats(final_status, reasons)
        
        # Draw status information
        fps = self._calculate_fps()
        draw_status_info(processed_frame, reasons, fps)
        
        return processed_frame
    
    def _update_stats(self, status: str, reasons: List[str]):
        """Update frame processing statistics."""
        if status != "Safe":
            self.stats.unsafe_frames += 1
        
        self.stats.total_frames += 1
        self.stats.fps_queue.append(time.time())
    
    def _calculate_fps(self) -> float:
        """Calculate current FPS."""
        if len(self.stats.fps_queue) <= 1:
            return 20.0
        return len(self.stats.fps_queue) / (self.stats.fps_queue[-1] - self.stats.fps_queue[0])
    
    def _stream_frame(self, streamer_process, frame: np.ndarray):
        """Stream frame to output process."""
        try:
            if streamer_process and streamer_process.stdin:
                streamer_process.stdin.write(frame.tobytes())
        except BrokenPipeError:
            if streamer_process:
                streamer_process.stdin.close()
                streamer_process.wait()
            return start_gstreamer_process(self.stream_id)
        
        return streamer_process
    
    def _handle_recording(self, frame: np.ndarray):
        """Handle video recording logic."""
        # Check if we should start recording
        if (not self.event_processor.recording_state.is_recording and 
            self.stats.total_frames % DEFAULT_FRAME_INTERVAL == 0):
            
            unsafe_ratio = self.stats.unsafe_frames / DEFAULT_FRAME_INTERVAL
            
            if self.event_processor.should_start_recording(unsafe_ratio, self.stats.last_event_time):
                # This would need the current reasons - you'd need to pass them in
                reasons = []  # You'd need to get current reasons from somewhere
                self.event_processor.start_recording(frame, reasons, self._calculate_fps())
                self.stats.last_event_time = time.time()
        
        # Write frame if recording
        if self.event_processor.recording_state.is_recording:
            self.event_processor.write_frame(frame)
            
            # Check if we should stop recording
            if self.event_processor.should_stop_recording():
                self.event_processor.stop_recording()
        
        # Reset frame counters
        if self.stats.total_frames % DEFAULT_FRAME_INTERVAL == 0:
            self.stats.unsafe_frames = 0
    
    def _health_monitor_loop(self):
        """Monitor stream health and trigger reconnections."""
        while not self.stop_event.is_set():
            time.sleep(1)
            
            if not self.pipeline.is_healthy():
                logging.warning(f"Stream health check failed for {self.stream_id}")
                self.pipeline.stop()