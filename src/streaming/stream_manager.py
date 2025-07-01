import logging
import threading
import time
from queue import Empty, Queue
from typing import List, Optional
from dataclasses import dataclass
from contextlib import contextmanager

import numpy as np

from config import FRAME_HEIGHT, FRAME_WIDTH, RECONNECT_WAIT_TIME_IN_SECS
from detection import draw_status_info
from detection.detector import Detector
from intrusion import detect_intrusion
from intrusion.tracking import SafeAreaTracker
from main.shared import safe_area_trackers
from socket_.socketio_instance import socketio
from utils import start_gstreamer_process

from .constants import (
    DEFAULT_FRAME_INTERVAL,
    MAX_FRAME_QUEUE_SIZE,
    MAX_RECONNECT_WAIT,
    NAMESPACE,
)
from .pipelines.manager import GStreamerPipeline
from .processing.event_processor import EventProcessor
from .types import PipelineConfig, StreamStats


@dataclass
class FrameProcessingResult:
    """Result of processing a single frame."""
    processed_frame: np.ndarray
    status: str
    reasons: List[str]
    person_bboxes: List
    fps: float


class StreamHealthMonitor:
    """Monitors stream health and handles reconnection logic."""
    
    def __init__(self, stream_id: str, pipeline: GStreamerPipeline):
        self.stream_id = stream_id
        self.pipeline = pipeline
        self.reconnect_attempt = 0
        self.stop_event = threading.Event()
    
    def start_monitoring(self):
        """Start the health monitoring loop."""
        threading.Thread(target=self._monitor_loop, daemon=True).start()
    
    def stop_monitoring(self):
        """Stop the health monitoring."""
        self.stop_event.set()
    
    def _monitor_loop(self):
        """Main health monitoring loop."""
        while not self.stop_event.is_set():
            time.sleep(1)
            if not self.pipeline.is_healthy():
                logging.warning(f"Stream health check failed for {self.stream_id}")
                self.pipeline.stop()
    
    def handle_reconnection(self, frame_callback) -> bool:
        """Handle pipeline reconnection with exponential backoff."""
        if self.pipeline.pipeline:
            return True
        
        if self.pipeline.create_and_start(frame_callback):
            self.reconnect_attempt = 0
            return True
        
        self.reconnect_attempt += 1
        wait_time = min(
            RECONNECT_WAIT_TIME_IN_SECS * min(self.reconnect_attempt, 5), 
            MAX_RECONNECT_WAIT
        )
        logging.warning(
            f"Reconnection attempt {self.reconnect_attempt} failed. "
            f"Retrying in {wait_time}s"
        )
        time.sleep(wait_time)
        return False


class FrameProcessor:
    """Handles frame processing logic."""
    
    def __init__(self, detector: Detector, safe_area_tracker: SafeAreaTracker, 
                 stream_id: str, ptz_autotrack: bool = False):
        self.detector = detector
        self.safe_area_tracker = safe_area_tracker
        self.stream_id = stream_id
        self.ptz_autotrack = ptz_autotrack
        self.ptz_auto_tracker = None
    
    def process_frame(self, frame: np.ndarray, fps: float) -> FrameProcessingResult:
        """Process a single frame through the complete pipeline."""
        # Run detection
        processed_frame, final_status, reasons, person_bboxes = self.detector.detect(frame)
        
        # Handle safe areas
        processed_frame = self._process_safe_areas(processed_frame, frame)
        
        # Check for intrusions
        final_status, reasons = self._check_intrusions(
            frame, person_bboxes, final_status, reasons
        )
        
        # Handle PTZ tracking
        self._handle_ptz_tracking(person_bboxes)
        
        # Draw status information
        draw_status_info(processed_frame, reasons, fps)
        
        return FrameProcessingResult(
            processed_frame=processed_frame,
            status=final_status,
            reasons=reasons,
            person_bboxes=person_bboxes,
            fps=fps
        )
    
    def _process_safe_areas(self, processed_frame: np.ndarray, 
                          original_frame: np.ndarray) -> np.ndarray:
        """Process safe areas and draw them on the frame."""
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(
            original_frame
        )
        return self.safe_area_tracker.draw_safe_area_on_frame(
            processed_frame, transformed_hazard_zones
        )
    
    def _check_intrusions(self, frame: np.ndarray, person_bboxes: List,
                         status: str, reasons: List[str]) -> tuple[str, List[str]]:
        """Check for intrusions and emit alerts."""
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
        intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
        
        if intruders:
            status = "Unsafe"
            reasons.append("intrusion")
            self._emit_intrusion_alert()
        
        return status, reasons
    
    def _emit_intrusion_alert(self):
        """Emit intrusion alert via socket."""
        socketio.emit(
            f"alert-{self.stream_id}",
            {"type": "intrusion"},
            namespace=NAMESPACE,
            room=self.stream_id
        )
    
    def _handle_ptz_tracking(self, person_bboxes: List):
        """Handle PTZ auto-tracking if enabled."""
        if self.ptz_autotrack and self.ptz_auto_tracker:
            self.ptz_auto_tracker.track(FRAME_WIDTH, FRAME_HEIGHT, person_bboxes)


class StreamRecorder:
    """Handles video recording logic."""
    
    def __init__(self, event_processor: EventProcessor, stats: StreamStats):
        self.event_processor = event_processor
        self.stats = stats
    
    def handle_recording(self, frame: np.ndarray, processing_result: FrameProcessingResult):
        """Handle recording logic for the current frame."""
        self._check_start_recording(frame, processing_result)
        self._write_frame_if_recording(frame)
        self._check_stop_recording()
        self._reset_counters_if_needed()
    
    def _check_start_recording(self, frame: np.ndarray, 
                             processing_result: FrameProcessingResult):
        """Check if recording should be started."""
        if (not self.event_processor.recording_state.is_recording and
            self.stats.total_frames % DEFAULT_FRAME_INTERVAL == 0):
            
            unsafe_ratio = self.stats.unsafe_frames / DEFAULT_FRAME_INTERVAL
            
            if self.event_processor.should_start_recording(
                unsafe_ratio, self.stats.last_event_time
            ):
                self.event_processor.start_recording(
                    frame, processing_result.reasons, processing_result.fps
                )
                self.stats.last_event_time = time.time()
    
    def _write_frame_if_recording(self, frame: np.ndarray):
        """Write frame to recording if active."""
        if self.event_processor.recording_state.is_recording:
            self.event_processor.write_frame(frame)
    
    def _check_stop_recording(self):
        """Check if recording should be stopped."""
        if (self.event_processor.recording_state.is_recording and
            self.event_processor.should_stop_recording()):
            self.event_processor.stop_recording()
    
    def _reset_counters_if_needed(self):
        """Reset frame counters at interval boundaries."""
        if self.stats.total_frames % DEFAULT_FRAME_INTERVAL == 0:
            self.stats.unsafe_frames = 0


class StreamOutputManager:
    """Manages stream output and streaming."""
    
    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        self.streamer_process = None
    
    @contextmanager
    def get_streamer_process(self):
        """Context manager for streamer process."""
        if not self.streamer_process:
            self.streamer_process = start_gstreamer_process(self.stream_id)
        
        try:
            yield self.streamer_process
        except BrokenPipeError:
            self._restart_streamer_process()
            yield self.streamer_process
    
    def stream_frame(self, frame: np.ndarray):
        """Stream frame to output process."""
        with self.get_streamer_process() as process:
            if process and process.stdin:
                process.stdin.write(frame.tobytes())
    
    def _restart_streamer_process(self):
        """Restart the streamer process."""
        if self.streamer_process:
            self.streamer_process.stdin.close()
            self.streamer_process.wait()
        self.streamer_process = start_gstreamer_process(self.stream_id)
    
    def cleanup(self):
        """Clean up streaming resources."""
        if self.streamer_process:
            self.streamer_process.stdin.close()
            self.streamer_process.wait()


class StreamManager:
    """Main class for managing RTSP stream processing."""
    
    def __init__(self, rtsp_link: str, model_name: str, stream_id: str, 
                 ptz_autotrack: bool = False):
        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        self.ptz_autotrack = ptz_autotrack
        
        # Initialize core components
        self._initialize_components()
        
        # Initialize managers
        self._initialize_managers()
        
        # Threading and state management
        self.frame_buffer = Queue(maxsize=MAX_FRAME_QUEUE_SIZE)
        self.running = False
        self.stop_event = threading.Event()
        self.threads: List[threading.Thread] = []
    
    def _initialize_components(self):
        """Initialize core detection and tracking components."""
        self.detector = Detector(self.model_name)
        self.safe_area_tracker = SafeAreaTracker()
        self.event_processor = EventProcessor(self.stream_id, self.model_name)
        self.stats = StreamStats()
        
        # Pipeline configuration
        pipeline_config = PipelineConfig(
            rtsp_link=self.rtsp_link,
            sink_name=f"sink_{self.stream_id}"
        )
        self.pipeline = GStreamerPipeline(pipeline_config, self.stream_id)
        
        # Register safe area tracker
        safe_area_trackers[self.stream_id] = self.safe_area_tracker
    
    def _initialize_managers(self):
        """Initialize management components."""
        self.health_monitor = StreamHealthMonitor(self.stream_id, self.pipeline)
        self.frame_processor = FrameProcessor(
            self.detector, self.safe_area_tracker, self.stream_id, self.ptz_autotrack
        )
        self.recorder = StreamRecorder(self.event_processor, self.stats)
        self.output_manager = StreamOutputManager(self.stream_id)
    
    def start_stream(self):
        """Start the stream processing."""
        self.running = True
        self.stop_event.clear()
        
        self.threads = [
            threading.Thread(target=self._frame_capture_loop, daemon=True),
            threading.Thread(target=self._frame_processing_loop, daemon=True),
        ]
        
        for thread in self.threads:
            thread.start()
        
        self.health_monitor.start_monitoring()
    
    def stop_streaming(self):
        """Stop the stream processing."""
        self.running = False
        self.stop_event.set()
        
        # Stop all components
        self.pipeline.stop()
        self.health_monitor.stop_monitoring()
        self.output_manager.cleanup()
        
        # Wait for threads to finish
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
    
    def _frame_capture_loop(self):
        """Main loop for capturing frames from RTSP stream."""
        while not self.stop_event.is_set():
            if not self.health_monitor.handle_reconnection(self._on_frame_received):
                continue
            
            # Main capture loop
            while not self.stop_event.is_set() and self.pipeline.pipeline:
                time.sleep(0.1)
                
                # Pipeline health is monitored by health_monitor
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
        while not self.stop_event.is_set():
            try:
                frame = self.frame_buffer.get(timeout=0.5)
                self._process_single_frame(frame)
                
            except Empty:
                continue
            except Exception as e:
                logging.error(f"Error in frame processing: {e}")
                time.sleep(0.1)
    
    def _process_single_frame(self, frame: np.ndarray):
        """Process a single frame through the complete pipeline."""
        # Calculate FPS
        fps = self._calculate_fps()
        
        # Process frame
        processing_result = self.frame_processor.process_frame(frame, fps)
        
        # Update statistics
        self._update_stats(processing_result.status, processing_result.reasons)
        
        # Stream processed frame
        self.output_manager.stream_frame(processing_result.processed_frame)
        
        # Handle recording
        self.recorder.handle_recording(frame, processing_result)
    
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
        return len(self.stats.fps_queue) / (
            self.stats.fps_queue[-1] - self.stats.fps_queue[0]
        )