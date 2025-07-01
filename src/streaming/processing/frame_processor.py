from typing import List, Tuple
import numpy as np
from config import FRAME_HEIGHT, FRAME_WIDTH
from detection import draw_status_info
from detection.detector import Detector
from intrusion import detect_intrusion
from intrusion.tracking import SafeAreaTracker
from socket_.socketio_instance import socketio
from ..constants import NAMESPACE
from ..types import FrameProcessingResult

class FrameProcessor:
    """Handles frame processing logic."""
    
    def __init__(self, detector: Detector, safe_area_tracker: SafeAreaTracker, 
                 stream_id: str, ptz_autotrack: bool = False):
        self.detector = detector
        self.safe_area_tracker = safe_area_tracker
        self.stream_id = stream_id
        self.ptz_autotrack = ptz_autotrack
        self.ptz_auto_tracker = None
    
    def process_frame(self, frame: np.ndarray, fps: float) -> FrameProcessingResult:
        """Process a single frame through the complete pipeline."""
        # Run detection
        processed_frame, final_status, reasons, person_bboxes = self.detector.detect(frame)
        
        # Handle safe areas
        processed_frame = self._process_safe_areas(processed_frame, frame)
        
        # Check for intrusions
        final_status, reasons = self._check_intrusions(
            frame, person_bboxes or [], final_status, reasons
        )
        
        # Handle PTZ tracking
        self._handle_ptz_tracking(person_bboxes or [])
        
        # Draw status information
        draw_status_info(processed_frame, reasons, fps)
        
        return FrameProcessingResult(
            processed_frame=processed_frame,
            status=final_status,
            reasons=[reasons] if isinstance(reasons, str) else reasons,
            person_bboxes=person_bboxes or [],
            fps=fps
        )
    
    def _process_safe_areas(self, processed_frame: np.ndarray, 
                          original_frame: np.ndarray) -> np.ndarray:
        """Process safe areas and draw them on the frame."""
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(
            original_frame
        )
        return self.safe_area_tracker.draw_safe_area_on_frame(
            processed_frame, transformed_hazard_zones
        )
    
    def _check_intrusions(self, frame: np.ndarray, person_bboxes: List,
                         status: str, reasons: List[str]) -> Tuple[str, List[str]]:
        """Check for intrusions and emit alerts."""
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
        intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
        
        if intruders:
            status = "Unsafe"
            reasons.append("intrusion")
            self._emit_intrusion_alert()
        
        return status, reasons
    
    def _emit_intrusion_alert(self):
        """Emit intrusion alert via socket."""
        socketio.emit(
            f"alert-{self.stream_id}",
            {"type": "intrusion"},
            namespace=NAMESPACE,
            room=self.stream_id # pyright: ignore[reportCallIssue]
        )
    
    def _handle_ptz_tracking(self, person_bboxes: List):
        """Handle PTZ auto-tracking if enabled."""
        if self.ptz_autotrack and self.ptz_auto_tracker:
            self.ptz_auto_tracker.track(FRAME_WIDTH, FRAME_HEIGHT, person_bboxes)
