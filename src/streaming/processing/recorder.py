import time
import numpy as np
from typing import TYPE_CHECKING
from ..constants import DEFAULT_FRAME_INTERVAL
from ..types import FrameProcessingResult
from .event_processor import EventProcessor
from ..types import StreamStats


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