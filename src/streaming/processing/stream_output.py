import numpy as np
from contextlib import contextmanager
from utils.media_processing import start_gstreamer_process

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
            self.streamer_process.stdin.close() # pyright: ignore[reportOptionalMemberAccess]
            self.streamer_process.wait()
        self.streamer_process = start_gstreamer_process(self.stream_id)
    
    def cleanup(self):
        """Clean up streaming resources."""
        if self.streamer_process:
            self.streamer_process.stdin.close() # pyright: ignore[reportOptionalMemberAccess]
            self.streamer_process.wait()