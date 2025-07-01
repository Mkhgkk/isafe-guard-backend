import os
import gi # pyright: ignore[reportMissingImports]

os.environ["GST_DEBUG"] = os.getenv("GST_DEBUG", "1")
gi.require_version('Gst', '1.0')

from gi.repository import Gst # pyright: ignore[reportMissingImports]

if not Gst.is_initialized():
    Gst.init(None)

from .stream_manager import StreamManager
from .types import (
    ConnectionState,
    PipelineConfig, 
    RecordingState,
    StreamStats
)
from .exceptions import (
    StreamingError,
    PipelineError,
    ConnectionError
)

__all__ = [
    'StreamManager',
    
    'PipelineConfig',
    'RecordingState', 
    'StreamStats',
    'ConnectionState',
    
    'StreamingError',
    'PipelineError', 
    'ConnectionError',
]