from utils.logging_config import get_logger, log_event
import threading
import time
from queue import Empty, Queue
from typing import List

import numpy as np

from detection import draw_status_info
from detection.detector import Detector
from intrusion.tracking import SafeAreaTracker
from main.shared import safe_area_trackers

from .constants import MAX_FRAME_QUEUE_SIZE, INFERENCE_INTERVAL

from .pipelines.manager import GStreamerPipeline
from .processing import (
    FrameProcessor,
    EventProcessor,
    StreamRecorder,
    StreamOutputManager,
)

from .types import PipelineConfig, StreamStats, FrameProcessingResult
from .health import StreamHealthMonitor

from events.api import emit_event, emit_dynamic_event
from events.events import EventType
from config import FRAME_WIDTH, FRAME_HEIGHT


class StreamManager:
    """Main class for managing RTSP stream processing."""

    def __init__(
        self,
        rtsp_link: str,
        model_name: str,
        stream_id: str,
        ptz_autotrack: bool = False,
        intrusion_detection: bool = False,
        saving_video: bool = True,
    ):
        self.stream_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name
        self.intrusion_detection = intrusion_detection
        self.saving_video = saving_video

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

        if hasattr(self, "frame_processor"):
            self.frame_processor.ptz_autotrack = value
            log_event(
                self.logger,
                "info",
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
        if value is not None and hasattr(self, "frame_processor"):
            self.frame_processor.ptz_auto_tracker = value
            log_event(
                self.logger,
                "info",
                "PTZ auto tracker attached to frame processor",
                event_type="ptz_tracker_attached",
                stream_id=self.stream_id,
            )
        elif value is None and hasattr(self, "frame_processor"):
            self.frame_processor.ptz_auto_tracker = None
            log_event(
                self.logger,
                "info",
                "PTZ auto tracker detached from frame processor",
                event_type="ptz_tracker_detached",
                stream_id=self.stream_id,
            )

    def set_intrusion_detection(self, enabled: bool):
        """Update the intrusion detection setting dynamically."""
        self.intrusion_detection = enabled
        if hasattr(self, "frame_processor"):
            self.frame_processor.set_intrusion_detection(enabled)
            log_event(
                self.logger,
                "info",
                f"Intrusion detection {'enabled' if enabled else 'disabled'} for stream {self.stream_id}",
                event_type="intrusion_detection_updated",
                stream_id=self.stream_id,
            )

    def set_saving_video(self, enabled: bool):
        """Update the saving video setting dynamically."""
        self.saving_video = enabled
        if hasattr(self, "recorder"):
            self.recorder.set_saving_video(enabled)
            # If disabling saving video, stop any current recording
            if (
                not enabled
                and self.recorder.event_processor.recording_state.is_recording
            ):
                self.recorder.event_processor.stop_recording()
                log_event(
                    self.logger,
                    "info",
                    f"Stopped active recording due to saving video being disabled for stream {self.stream_id}",
                    event_type="recording_stopped",
                    stream_id=self.stream_id,
                )
        log_event(
            self.logger,
            "info",
            f"Saving video {'enabled' if enabled else 'disabled'} for stream {self.stream_id}",
            event_type="saving_video_updated",
            stream_id=self.stream_id,
        )

    def _initialize_components(self):
        """Initialize core detection and tracking components."""
        self.detector = Detector(self.model_name, self.stream_id)
        self.safe_area_tracker = SafeAreaTracker()
        self.event_processor = EventProcessor(self.stream_id, self.model_name)
        self.stats = StreamStats()

        # Pipeline configuration
        pipeline_config = PipelineConfig(
            rtsp_link=self.rtsp_link, sink_name=f"sink_{self.stream_id}"
        )
        self.pipeline = GStreamerPipeline(pipeline_config, self.stream_id)

        # Register safe area tracker
        safe_area_trackers[self.stream_id] = self.safe_area_tracker

    def _initialize_managers(self):
        """Initialize management components."""
        self.health_monitor = StreamHealthMonitor(self.stream_id, self.pipeline)
        self.frame_processor = FrameProcessor(
            self.detector,
            self.safe_area_tracker,
            self.stream_id,
            self.ptz_autotrack,
            self.intrusion_detection,
        )
        self.recorder = StreamRecorder(
            self.event_processor, self.stats, self.saving_video
        )
        self.output_manager = StreamOutputManager(self.stream_id)

        # Frame rate limiting for inference
        self.last_inference_time = 0
        self.inference_interval = INFERENCE_INTERVAL

        # Separate FPS tracking for streaming (independent of inference)
        self.streaming_fps_queue = []
        self.streaming_fps_max_samples = 30  # Track last 30 frames for FPS calculation

        # Cache for detection results to reuse on frames without inference
        self.cached_detection_results = None

        # Store last raw frame for frame retrieval
        self.last_raw_frame = None

    def get_frame(self):
        """Get the current unprocessed frame from the stream.

        Returns:
            np.ndarray: The last raw unprocessed frame, or None if no frame has been captured yet.
        """
        if self.last_raw_frame is not None:
            return self.last_raw_frame.copy()
        return None

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

        # Clean up detector to free GPU memory
        if hasattr(self, "detector") and self.detector:
            self.detector.cleanup()
            self.detector = None

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
                    log_event(
                        self.logger,
                        "warning",
                        f"Pipeline unhealthy for {self.stream_id}, restarting",
                        event_type="warning",
                    )
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
                log_event(
                    self.logger,
                    "error",
                    f"Error in frame processing: {e}",
                    event_type="error",
                )
                time.sleep(0.1)

    def _process_single_frame(self, frame: np.ndarray):
        """Process a single frame through the complete pipeline."""
        # Store the raw frame for retrieval
        self.last_raw_frame = frame

        current_time = time.time()
        fps = self._calculate_fps()

        # Update and emit connection speed data
        self._update_and_emit_connection_speed()

        # Check if enough time has passed for inference
        should_run_inference = (
            current_time - self.last_inference_time
        ) >= self.inference_interval

        if should_run_inference:
            # Run full inference processing
            processing_result, cached_results = self.frame_processor.process_frame(
                frame, fps
            )
            self._update_stats(processing_result.status, processing_result.reasons)
            self.last_inference_time = current_time

            # Cache detection results for reuse on non-inference frames
            self.cached_detection_results = cached_results
            self.last_processing_result = processing_result
        else:
            # Skip inference, draw cached detections on current frame
            if self.cached_detection_results is not None:
                # Process frame with cached detection results
                processing_result = (
                    self.frame_processor.process_frame_with_cached_results(
                        frame, fps, self.cached_detection_results
                    )
                )
            else:
                # No cached result yet, create minimal result
                display_frame = frame.copy()
                draw_status_info(display_frame, [], fps, 0, "Safe")
                processing_result = FrameProcessingResult(
                    processed_frame=display_frame,
                    status="Safe",
                    reasons=[],
                    person_bboxes=[],
                    fps=fps,
                )

        # Always stream and record frames
        self.output_manager.stream_frame(processing_result.processed_frame)
        self.recorder.handle_recording(
            processing_result.processed_frame, processing_result
        )

    def _update_stats(self, status: str, reasons: List[str]):
        """Update frame processing statistics."""
        if status != "Safe":
            self.stats.unsafe_frames += 1

        self.stats.total_frames += 1
        self.stats.fps_queue.append(time.time())

    def _calculate_fps(self) -> float:
        """Calculate current streaming FPS (not inference FPS)."""
        current_time = time.time()

        # Add current timestamp to the queue
        self.streaming_fps_queue.append(current_time)

        # Keep only the last N samples
        if len(self.streaming_fps_queue) > self.streaming_fps_max_samples:
            self.streaming_fps_queue.pop(0)

        # Need at least 2 samples to calculate FPS
        if len(self.streaming_fps_queue) <= 1:
            return 20.0

        # Calculate FPS based on time difference
        time_span = self.streaming_fps_queue[-1] - self.streaming_fps_queue[0]
        if time_span > 0:
            return (len(self.streaming_fps_queue) - 1) / time_span

        return 20.0

    def _update_and_emit_connection_speed(self):
        """Calculate and emit connection speed statistics."""
        current_time = time.time()

        # Get frame latency from pipeline
        frame_latency = self.pipeline.get_frame_latency()

        if frame_latency > 0:
            # Add to latency queue
            self.stats.frame_latencies.append(frame_latency)

            # Calculate average latency
            if len(self.stats.frame_latencies) > 0:
                self.stats.average_latency = sum(self.stats.frame_latencies) / len(
                    self.stats.frame_latencies
                )

                # Calculate connection speed (fps based on frame intervals)
                if self.stats.average_latency > 0:
                    self.stats.current_speed = 1000.0 / self.stats.average_latency
                else:
                    self.stats.current_speed = 0.0

        # Get actual bitrate from GStreamer bitrate element
        bitrate_bps = self.pipeline.get_bitrate()

        if bitrate_bps > 0:
            # Convert bitrate from bits per second to kbps and mbps
            self.stats.bandwidth_kbps = bitrate_bps / 1000
            self.stats.bandwidth_mbps = bitrate_bps / 1000000

        # Emit connection speed data every second
        if current_time - self.stats.last_speed_emit_time >= 1.0:
            self.stats.last_speed_emit_time = current_time

            # emit_event(
            #     event_type=EventType.CONNECTION_SPEED,
            #     data={
            #         "stream_id": self.stream_id,
            #         "latency_ms": round(frame_latency, 2) if frame_latency > 0 else 0,
            #         "average_latency_ms": round(self.stats.average_latency, 2),
            #         "connection_fps": round(self.stats.current_speed, 2),
            #         "bandwidth_kbps": round(self.stats.bandwidth_kbps, 2),
            #         "bandwidth_mbps": round(self.stats.bandwidth_mbps, 2),
            #     },
            #     room=self.stream_id,
            #     broadcast=False,
            # )

            emit_dynamic_event(
                base_event_type=EventType.CONNECTION_SPEED,
                data={
                    "latency_ms": round(frame_latency, 2) if frame_latency > 0 else 0,
                    "average_latency_ms": round(self.stats.average_latency, 2),
                    "connection_fps": round(self.stats.current_speed, 2),
                    "bandwidth_kbps": round(self.stats.bandwidth_kbps, 2),
                    "bandwidth_mbps": round(self.stats.bandwidth_mbps, 2),
                },
                room=self.stream_id,
                identifier=self.stream_id,
                broadcast=False,
            )
