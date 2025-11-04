from typing import List, Tuple
import numpy as np
from config import FRAME_HEIGHT, FRAME_WIDTH
from detection import draw_status_info
from detection.detector import Detector
from intrusion import detect_intrusion
from intrusion.tracking import SafeAreaTracker
from events import emit_dynamic_event, EventType
from ..types import FrameProcessingResult

class FrameProcessor:
    """Handles frame processing logic."""
    
    def __init__(self, detector: Detector, safe_area_tracker: SafeAreaTracker, 
                 stream_id: str, ptz_autotrack: bool = False, intrusion_detection: bool = False):
        self.detector = detector
        self.safe_area_tracker = safe_area_tracker
        self.stream_id = stream_id
        self.ptz_autotrack = ptz_autotrack
        self.ptz_auto_tracker = None
        self.intrusion_detection = intrusion_detection
    
    def process_frame(self, frame: np.ndarray, fps: float) -> tuple[FrameProcessingResult, any]:
        """Process a single frame through the complete pipeline."""
        # Run detection
        processed_frame, final_status, reasons, person_bboxes, cached_results = self.detector.detect(frame)

        # Handle safe areas
        processed_frame = self._process_safe_areas(processed_frame, frame)

        # Check for intrusions
        final_status, reasons = self._check_intrusions(
            frame, person_bboxes or [], final_status, reasons
        )

        # Handle PTZ tracking
        self._handle_ptz_tracking(person_bboxes or [])

        # Draw status information
        draw_status_info(processed_frame, reasons, fps, len(person_bboxes or []), final_status)

        result = FrameProcessingResult(
            processed_frame=processed_frame,
            status=final_status,
            reasons=[reasons] if isinstance(reasons, str) else reasons,
            person_bboxes=person_bboxes or [],
            fps=fps
        )

        return result, cached_results

    def process_frame_with_cached_results(self, frame: np.ndarray, fps: float, cached_results: any) -> FrameProcessingResult:
        """Process a frame using cached detection results without running inference."""
        # Process cached detection results
        processed_frame, final_status, reasons, person_bboxes = self.detector.process_cached_results(frame, cached_results)

        # Handle safe areas
        processed_frame = self._process_safe_areas(processed_frame, frame)

        # Check for intrusions (using cached person bboxes)
        final_status, reasons = self._check_intrusions(
            frame, person_bboxes or [], final_status, reasons
        )

        # Note: PTZ tracking is skipped for cached frames to avoid duplicate tracking

        # Draw status information
        draw_status_info(processed_frame, reasons, fps, len(person_bboxes or []), final_status)

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
        # Skip drawing safe areas if intrusion detection is disabled
        if not self.intrusion_detection:
            return processed_frame
            
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(
            original_frame
        )
        return self.safe_area_tracker.draw_safe_area_on_frame(
            processed_frame, transformed_hazard_zones
        )
    
    def _check_intrusions(self, frame: np.ndarray, person_bboxes: List,
                         status: str, reasons: List[str]) -> Tuple[str, List[str]]:
        """Check for intrusions and emit alerts."""
        # Skip intrusion detection if it's disabled
        if not self.intrusion_detection:
            return status, reasons
            
        transformed_hazard_zones = self.safe_area_tracker.get_transformed_safe_areas(frame)
        intruders = detect_intrusion(transformed_hazard_zones, person_bboxes)
        
        if intruders:
            status = "Unsafe"
            reasons.append("intrusion")
            self._emit_intrusion_alert()
        
        return status, reasons
    
    def _emit_intrusion_alert(self):
        """Emit intrusion alert via socket."""

        data = {"type": "intrusion"}
        emit_dynamic_event(base_event_type=EventType.ALERT, identifier=self.stream_id, data=data, room=self.stream_id)
    
    def _handle_ptz_tracking(self, person_bboxes: List):
        """Handle PTZ auto-tracking if enabled."""
        if self.ptz_autotrack and self.ptz_auto_tracker:
            self.ptz_auto_tracker.track(FRAME_WIDTH, FRAME_HEIGHT, person_bboxes)
    
    def set_intrusion_detection(self, enabled: bool):
        """Update the intrusion detection setting dynamically."""
        self.intrusion_detection = enabled
