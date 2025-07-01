import datetime
import logging
import threading
import time
from typing import List, Tuple

import numpy as np
from bson import ObjectId  # pyright: ignore[reportMissingImports]

from main.event.model import Event
from utils import create_video_writer
from utils.notifications import send_email_notification, send_watch_notification

from ..constants import DEFAULT_EVENT_COOLDOWN, DEFAULT_UNSAFE_RATIO_THRESHOLD
from ..types import RecordingState

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
