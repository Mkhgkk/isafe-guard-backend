from dataclasses import dataclass
import numpy as np
from typing import List
from enum import Enum
from typing import Optional, Any
from collections import deque

from config import FRAME_HEIGHT, FRAME_WIDTH
from .constants import MAX_BUFFER_SIZE, DEFAULT_RECORD_DURATION, FPS_QUEUE_SIZE

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
    fps_queue: deque = None # type: ignore
    last_event_time: float = 0
    
    def __post_init__(self):
        if self.fps_queue is None:
            self.fps_queue = deque(maxlen=FPS_QUEUE_SIZE)

@dataclass
class FrameProcessingResult:
    """Result of processing a single frame."""
    processed_frame: np.ndarray
    status: str
    reasons: List[str]
    person_bboxes: List
    fps: float