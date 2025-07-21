from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)
import time
from typing import Optional
import numpy as np

from gi.repository import Gst # pyright: ignore[reportMissingImports]
import os

# Set GStreamer debug level and redirect to Python logging
os.environ.setdefault('GST_DEBUG', '2')
os.environ.setdefault('GST_DEBUG_NO_COLOR', '1')

# Global flag to track if debug handler is installed
_debug_handler_installed = False

def _gst_debug_handler(category, level, file, function, line, obj, msg, user_data):
    """Custom GStreamer debug handler to redirect to Python logging."""
    level_map = {
        Gst.DebugLevel.ERROR: "error",
        Gst.DebugLevel.WARNING: "warning", 
        Gst.DebugLevel.INFO: "info",
        Gst.DebugLevel.DEBUG: "debug"
    }
    
    python_level = level_map.get(level, "info")
    category_name = category.get_name() if category else "gstreamer"
    
    log_event(
        logger, 
        python_level,
        f"GStreamer [{category_name}] {msg}",
        event_type="gstreamer_debug",
        extra={
            "category": category_name,
            "file": file,
            "function": function,
            "line": line
        }
    )

def _install_gst_debug_handler():
    """Install GStreamer debug handler if not already installed."""
    global _debug_handler_installed
    if not _debug_handler_installed:
        Gst.init(None)  # Ensure GStreamer is initialized
        Gst.debug_set_default_threshold(Gst.DebugLevel.WARNING)
        Gst.debug_add_log_function(_gst_debug_handler, None)
        _debug_handler_installed = True
        log_event(logger, "info", "GStreamer debug handler installed", event_type="gstreamer_debug_setup")

from ..types import PipelineConfig
from .builder import PipelineBuilder
from ..constants import DEFAULT_FRAME_TIMEOUT

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
        
        # Install GStreamer debug handler
        _install_gst_debug_handler()
        
    def create_and_start(self, frame_callback) -> bool:
        """Create and start the GStreamer pipeline."""
        self.frame_callback = frame_callback
        
        # Choose pipeline type based on previous failures
        if self.use_alternative:
            pipeline_str = PipelineBuilder.create_alternative_pipeline(self.config)
            log_event(logger, "info", f"Using alternative pipeline for {self.stream_id}", event_type="info")
        else:
            pipeline_str = PipelineBuilder.create_primary_pipeline(self.config)
            
        log_event(logger, "info", f"Creating pipeline: {pipeline_str}", event_type="info")
        
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
            return self._configure_pipeline()
        except Exception as e:
            log_event(logger, "error", f"Error creating pipeline: {e}", event_type="error")
            self.connection_trials += 1
            
            # Switch to alternative after multiple failures
            if self.connection_trials >= 2 and not self.use_alternative:
                self.use_alternative = True
                log_event(logger, "info", "Switching to alternative pipeline on next attempt", event_type="info")
                
            return False
    
    def _configure_pipeline(self) -> bool:
        """Configure the pipeline elements and start it."""
        appsink = self.pipeline.get_by_name(self.config.sink_name) # pyright: ignore[reportOptionalMemberAccess]
        if not appsink:
            log_event(logger, "error", f"Failed to get appsink element '{self.config.sink_name}'", event_type="error")
            return False
            
        # Configure appsink
        appsink.set_property("emit-signals", True)
        appsink.set_property("max-buffers", self.config.max_buffers)
        appsink.set_property("drop", True)
        appsink.set_property("sync", False)
        appsink.connect("new-sample", self._on_new_sample)
        
        # Connect bus messages
        bus = self.pipeline.get_bus() # pyright: ignore[reportOptionalMemberAccess]
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        
        # Start pipeline
        ret = self.pipeline.set_state(Gst.State.PLAYING) # pyright: ignore[reportOptionalMemberAccess]
        if ret == Gst.StateChangeReturn.FAILURE:
            log_event(logger, "error", f"Failed to start pipeline for stream {self.stream_id}", event_type="error")
            return False
            
        if ret == Gst.StateChangeReturn.ASYNC:
            ret = self.pipeline.get_state(Gst.CLOCK_TIME_NONE) # pyright: ignore[reportOptionalMemberAccess]
            if ret[0] != Gst.StateChangeReturn.SUCCESS:
                log_event(logger, "error", f"Pipeline state change failed for stream {self.stream_id}", event_type="error")
                return False
                
        log_event(logger, "info", f"Successfully started GStreamer pipeline for {self.stream_id}", event_type="info")
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
            log_event(logger, "error", f"Error in _on_new_sample: {e}", event_type="error")
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
            log_event(logger, "warning", "Failed to map buffer", event_type="warning")
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
            log_event(logger, "warning", f"End of stream for {self.stream_id}", event_type="warning")
        elif msg_type == Gst.MessageType.WARNING:
            self._handle_warning_message(message)
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            self._handle_state_change_message(message)
    
    def _handle_error_message(self, message):
        """Handle error messages from GStreamer."""
        err, debug = message.parse_error()
        log_event(logger, "error", f"GStreamer error: {err.message}, {debug}", event_type="error")
        
        # Check for ONVIF metadata issues
        if "ONVIF.METADATA" in str(debug):
            log_event(logger, "warning", "ONVIF metadata issue detected", event_type="warning")
            self.use_alternative = True
    
    def _handle_warning_message(self, message):
        """Handle warning messages from GStreamer."""
        warn, debug = message.parse_warning()
        log_event(logger, "warning", f"GStreamer warning: {warn.message}, {debug}", event_type="warning")
    
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
        log_event(logger, "info", f"Pipeline state for {self.stream_id}: {old_name} -> {new_name}", event_type="info")
        
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