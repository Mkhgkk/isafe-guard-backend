"""
Helmet detection and temporal tracking for worker safety monitoring.

This module provides helmet detection with temporal smoothing to reduce
false positives from transient occlusions or detection failures.
"""

import time
from typing import Dict, List


# Helmet detection constants
HELMET_TRACKING_WINDOW = 90  # Number of recent frames to consider
HELMET_CONFIDENCE_THRESHOLD = 0.2  # Ratio of frames with helmet needed to be considered "safe"
MAX_MISSING_FRAMES = 50  # Allow up to 5 consecutive frames without detection before considering violation
GRACE_PERIOD_SECONDS = 5.0  # Time in seconds to suppress violation if previously safe

# Minimum person box size for reliable helmet detection
MIN_PERSON_BOX_WIDTH = 15  # Minimum width in pixels
MIN_PERSON_BOX_HEIGHT = 30  # Minimum height in pixels
MIN_PERSON_BOX_AREA = MIN_PERSON_BOX_WIDTH * MIN_PERSON_BOX_HEIGHT

# Helmet detection offset (pixels above person box to search for helmet)
HELMET_DETECTION_OFFSET = 20


class HelmetTracker:
    """Tracks helmet detection over time for workers.

    This class maintains a temporal history of helmet detections for each worker
    and uses confidence scoring to determine consistent violations. This approach
    reduces false positives from temporary occlusions or detection failures.

    Attributes:
        tracking_window: Number of recent frames to consider
        confidence_threshold: Minimum ratio of frames with helmet to be considered safe
        max_missing_frames: Maximum consecutive frames without helmet before violation
        _helmet_tracking: Nested dict storing helmet detection history per stream/worker
    """

    def __init__(
        self,
        tracking_window: int = HELMET_TRACKING_WINDOW,
        confidence_threshold: float = HELMET_CONFIDENCE_THRESHOLD,
        max_missing_frames: int = MAX_MISSING_FRAMES,
        grace_period_seconds: float = GRACE_PERIOD_SECONDS,
    ):
        """Initialize the helmet tracker.

        Args:
            tracking_window: Number of recent frames to consider (default: 90)
            confidence_threshold: Minimum helmet detection ratio (default: 0.7)
            max_missing_frames: Max consecutive missing frames (default: 5)
            grace_period_seconds: Grace period in seconds (default: 5.0)
        """
        self._helmet_tracking: Dict[str, Dict[int, Dict[str, List]]] = {}
        self._last_safe_time: Dict[str, Dict[int, float]] = {}
        self.tracking_window = tracking_window
        self.confidence_threshold = confidence_threshold
        self.max_missing_frames = max_missing_frames
        self.grace_period_seconds = grace_period_seconds

    def update(self, stream_id: str, worker_id: int, has_helmet: bool) -> None:
        """Update helmet detection history for a worker.

        Args:
            stream_id: Identifier for the video stream
            worker_id: Unique tracking ID for the worker
            has_helmet: True if helmet was detected in current frame
        """
        current_time = time.time()

        if stream_id not in self._helmet_tracking:
            self._helmet_tracking[stream_id] = {}

        if worker_id not in self._helmet_tracking[stream_id]:
            self._helmet_tracking[stream_id][worker_id] = {
                "helmet_detections": [],
                "timestamps": [],
            }

        worker_history = self._helmet_tracking[stream_id][worker_id]

        # Add current detection
        worker_history["helmet_detections"].append(has_helmet)
        worker_history["timestamps"].append(current_time)

        # Keep only recent detections within the tracking window
        if len(worker_history["helmet_detections"]) > self.tracking_window:
            worker_history["helmet_detections"].pop(0)
            worker_history["timestamps"].pop(0)

    def is_violation(self, stream_id: str, worker_id: int) -> bool:
        """Check if worker has a consistent helmet violation based on tracking history.

        A violation is flagged when:
        1. The worker has been tracked for at least max_missing_frames
        2. The helmet detection rate is below confidence_threshold
        3. There are at least max_missing_frames consecutive missing detections

        Args:
            stream_id: Identifier for the video stream
            worker_id: Unique tracking ID for the worker

        Returns:
            True if consistent violation detected, False otherwise
        """
        if (
            stream_id not in self._helmet_tracking
            or worker_id not in self._helmet_tracking[stream_id]
        ):
            return False

        worker_history = self._helmet_tracking[stream_id][worker_id]
        detections = worker_history["helmet_detections"]

        if len(detections) < self.max_missing_frames:
            return False  # Not enough data yet

        # Calculate recent helmet detection rate
        recent_detections = (
            detections[-self.tracking_window :]
            if len(detections) >= self.tracking_window
            else detections
        )
        helmet_rate = sum(recent_detections) / len(recent_detections)

        # Check for consecutive missing helmet detections
        consecutive_missing = 0
        for detection in reversed(recent_detections):
            if not detection:
                consecutive_missing += 1
            else:
                break

        # Return violation if helmet rate is below threshold AND there are consecutive missing detections
        is_raw_violation = (
            helmet_rate < self.confidence_threshold
            and consecutive_missing >= self.max_missing_frames
        )

        if not is_raw_violation:
            # Worker is considered safe, update last safe time
            if stream_id not in self._last_safe_time:
                self._last_safe_time[stream_id] = {}
            self._last_safe_time[stream_id][worker_id] = time.time()
            return False
        
        # If violation detected, check for grace period
        if stream_id in self._last_safe_time and worker_id in self._last_safe_time[stream_id]:
            last_safe = self._last_safe_time[stream_id][worker_id]
            time_since_safe = time.time() - last_safe
            if time_since_safe < self.grace_period_seconds:
                # Suppress violation during grace period
                return False

        return True

    def cleanup(self, stream_id: str) -> None:
        """Clean up helmet tracking data for a given stream.

        This should be called when a stream is closed to free memory.

        Args:
            stream_id: Identifier for the video stream to clean up
        """
        if stream_id in self._helmet_tracking:
            del self._helmet_tracking[stream_id]
        if stream_id in self._last_safe_time:
            del self._last_safe_time[stream_id]


def is_person_box_large_enough(
    box: List[int],
    min_width: int = MIN_PERSON_BOX_WIDTH,
    min_height: int = MIN_PERSON_BOX_HEIGHT,
    min_area: int = MIN_PERSON_BOX_AREA,
) -> bool:
    """Check if person bounding box is large enough for reliable helmet detection.

    Small or distant person boxes may not have sufficient resolution for accurate
    helmet detection, leading to false positives. This function filters out such cases.

    Args:
        box: Person bounding box [x1, y1, x2, y2]
        min_width: Minimum acceptable width in pixels (default: 30)
        min_height: Minimum acceptable height in pixels (default: 60)
        min_area: Minimum acceptable area in pixels² (default: 1800)

    Returns:
        True if box meets all size requirements, False otherwise
    """
    width = box[2] - box[0]
    height = box[3] - box[1]
    area = width * height

    return width >= min_width and height >= min_height and area >= min_area


def check_helmet_in_box(
    person_box: List[int],
    helmet_boxes: List[List[int]],
    offset: int = HELMET_DETECTION_OFFSET,
) -> bool:
    """Check if a helmet is detected within a person's bounding box.

    This function performs spatial overlap checking between a person box and
    helmet detections. A helmet is considered present if its center x-coordinate
    falls within the person's horizontal bounds and it's positioned near the
    person's head (accounting for offset).

    Args:
        person_box: Person bounding box [x1, y1, x2, y2]
        helmet_boxes: List of helmet bounding boxes [[x1, y1, x2, y2], ...]
        offset: Vertical offset above person box to search for helmet (default: 20)

    Returns:
        True if helmet detected within person box, False otherwise

    Example:
        >>> person_box = [100, 100, 200, 300]
        >>> helmet_boxes = [[120, 80, 180, 120]]
        >>> check_helmet_in_box(person_box, helmet_boxes)
        True
    """
    return any(
        person_box[0] <= (hat_box[0] + hat_box[2]) / 2 < person_box[2]
        and hat_box[1] >= person_box[1] - offset
        for hat_box in helmet_boxes
    )
