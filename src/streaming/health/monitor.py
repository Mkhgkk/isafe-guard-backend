import logging
import threading
import time
from config import RECONNECT_WAIT_TIME_IN_SECS
from ..constants import MAX_RECONNECT_WAIT
from ..pipelines.manager import GStreamerPipeline

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