from utils.logging_config import get_logger, log_event
import threading
import time
from queue import Empty, Queue
from typing import List

import numpy as np

from detection.detector import Detector
from intrusion.tracking import SafeAreaTracker
from main.shared import safe_area_trackers

from .constants import MAX_FRAME_QUEUE_SIZE

from .pipelines.manager import GStreamerPipeline
from .processing import FrameProcessor, EventProcessor, StreamRecorder, StreamOutputManager

from .types import PipelineConfig, StreamStats
from .health import StreamHealthMonitor

class StreamManager:
    """Main class for managing RTSP stream processing."""
    
    def __init__(self, rtsp_link: str, model_name: str, stream_id: str, 
                 ptz_autotrack: bool = False):
        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        
        # Initialize logger
        self.logger = get_logger(f"StreamManager.{stream_id}")
        
        # Initialize core components
        self._initialize_components()

        # Initialize private attributes
        self._ptz_autotrack = ptz_autotrack
        self._ptz_auto_tracker = None
        
        # Initialize managers
        self._initialize_managers()
        
        # Threading and state management
        self.frame_buffer = Queue(maxsize=MAX_FRAME_QUEUE_SIZE)
        self.running = False
        self.stop_event = threading.Event()
        self.threads: List[threading.Thread] = []

    @property
    def ptz_autotrack(self):
        """Get the PTZ autotrack boolean flag."""
        return self._ptz_autotrack
    
    @ptz_autotrack.setter
    def ptz_autotrack(self, value: bool):
        """Set the PTZ autotrack flag and update frame processor."""
        self._ptz_autotrack = value
        
        if hasattr(self, 'frame_processor'):
            self.frame_processor.ptz_autotrack = value
            log_event(
                self.logger, "info", 
                f"PTZ autotrack {'enabled' if value else 'disabled'}",
                event_type="ptz_autotrack_toggle",
                stream_id=self.stream_id,
                # enabled=value
            )    

    @property
    def ptz_auto_tracker(self):
        """Get the PTZ auto tracker."""
        return self._ptz_auto_tracker
    
    @ptz_auto_tracker.setter
    def ptz_auto_tracker(self, value):
        """Set the PTZ auto tracker and attach it to frame processor."""
        self._ptz_auto_tracker = value
        
        # Attach to frame processor when set
        if value is not None and hasattr(self, 'frame_processor'):
            self.frame_processor.ptz_auto_tracker = value
            log_event(
                self.logger, "info", 
                "PTZ auto tracker attached to frame processor",
                event_type="ptz_tracker_attached",
                stream_id=self.stream_id
            )
        elif value is None and hasattr(self, 'frame_processor'):
            self.frame_processor.ptz_auto_tracker = None
            log_event(
                self.logger, "info", 
                "PTZ auto tracker detached from frame processor",
                event_type="ptz_tracker_detached",
                stream_id=self.stream_id
            )
    
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
                
                # Monitor stream health
                if not self.pipeline.is_healthy():
                    log_event(self.logger, "warning", f"Pipeline unhealthy for {self.stream_id}, restarting", event_type="warning")
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
                log_event(self.logger, "error", f"Error in frame processing: {e}", event_type="error")
                time.sleep(0.1)
    
    def _process_single_frame(self, frame: np.ndarray):
        """Process a single frame through the complete pipeline."""
        fps = self._calculate_fps()

        processing_result = self.frame_processor.process_frame(frame, fps)
        self._update_stats(processing_result.status, processing_result.reasons)
        self.output_manager.stream_frame(processing_result.processed_frame)
        self.recorder.handle_recording(processing_result.processed_frame, processing_result)
    
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