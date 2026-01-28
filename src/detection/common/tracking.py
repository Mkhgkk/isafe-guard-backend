"""
Object tracking infrastructure for detection systems.

This module provides tracking management for objects across video streams,
including tracking history storage and movement detection utilities.
"""

import numpy as np
from collections import deque
from typing import Dict, List


class TrackingManager:
    """Manages tracking history for objects across streams.

    This class maintains a history of bounding boxes for tracked objects
    across multiple video streams, enabling temporal analysis like movement
    detection and trajectory tracking.

    Attributes:
        _track_history: Nested dict storing tracking data per stream and track ID
        _max_history_length: Maximum number of frames to keep in history
    """

    def __init__(self, max_history_length: int = 30):
        """Initialize the tracking manager.

        Args:
            max_history_length: Maximum number of frames to keep in history (default: 30)
        """
        self._track_history: Dict[str, Dict[int, deque]] = {}
        self._max_history_length = max_history_length

    def update(self, stream_id: str, track_id: int, bbox: List[int]) -> None:
        """Update tracking history for a tracked object.

        Args:
            stream_id: Identifier for the video stream
            track_id: Unique tracking ID for the object
            bbox: Bounding box as [x1, y1, x2, y2]
        """
        if stream_id not in self._track_history:
            self._track_history[stream_id] = {}

        if track_id not in self._track_history[stream_id]:
            self._track_history[stream_id][track_id] = deque(maxlen=self._max_history_length)

        self._track_history[stream_id][track_id].append(bbox)

    def get_history(self, stream_id: str, track_id: int) -> deque:
        """Get tracking history for a specific track.

        Args:
            stream_id: Identifier for the video stream
            track_id: Unique tracking ID for the object

        Returns:
            Deque of bounding boxes, empty deque if no history exists
        """
        if stream_id in self._track_history and track_id in self._track_history[stream_id]:
            return self._track_history[stream_id][track_id]
        return deque()

    def cleanup(self, stream_id: str) -> None:
        """Clean up tracking data for a given stream.

        This should be called when a stream is closed to free memory.

        Args:
            stream_id: Identifier for the video stream to clean up
        """
        if stream_id in self._track_history:
            del self._track_history[stream_id]

    def has_sufficient_history(self, stream_id: str, track_id: int, min_frames: int = 3) -> bool:
        """Check if a track has sufficient history for analysis.

        Args:
            stream_id: Identifier for the video stream
            track_id: Unique tracking ID for the object
            min_frames: Minimum number of frames required (default: 3)

        Returns:
            True if track has at least min_frames of history, False otherwise
        """
        history = self.get_history(stream_id, track_id)
        return len(history) >= min_frames


def is_vehicle_moving(history: deque, threshold: float = 10.0) -> bool:
    """Fast vehicle movement detection using displacement calculation.

    Calculates the displacement between the first and last bounding box
    centers in the tracking history to determine if a vehicle is moving.

    Args:
        history: Deque of bounding boxes [x1, y1, x2, y2]
        threshold: Movement threshold in pixels (default: 10.0)

    Returns:
        True if vehicle is moving (displacement > threshold), False otherwise

    Note:
        Requires at least 10 frames of history for reliable detection.
    """
    if len(history) < 10:
        return False

    first_box = history[0]
    last_box = history[-1]

    # Calculate center points
    first_center = np.array(
        [float(first_box[0] + first_box[2]) / 2, float(first_box[1] + first_box[3]) / 2]
    )
    last_center = np.array(
        [float(last_box[0] + last_box[2]) / 2, float(last_box[1] + last_box[3]) / 2]
    )

    # Calculate displacement
    displacement = np.linalg.norm(last_center - first_center)

    return bool(displacement > threshold)
