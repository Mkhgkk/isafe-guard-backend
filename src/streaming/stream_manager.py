import logging
import threading
import time
from queue import Empty, Queue
from typing import List

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
            streamer_process.stdin.close() # pyright: ignore[reportOptionalMemberAccess]
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
                room=self.stream_id # pyright: ignore[reportCallIssue]
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