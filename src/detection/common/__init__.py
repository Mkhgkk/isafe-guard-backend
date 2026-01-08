"""
Common detection utilities shared across multiple detectors.

This module provides reusable functionality for:
- Object tracking across frames (TrackingManager, is_vehicle_moving)
- Helmet detection and temporal tracking (HelmetTracker, check_helmet_in_box)
- Privacy-preserving face blurring (blur_face_region, should_blur_person)

Usage:
    from detection.common import TrackingManager, HelmetTracker, blur_face_region

    # Initialize tracking managers
    tracking_mgr = TrackingManager()
    helmet_tracker = HelmetTracker()

    # Update tracking for an object
    tracking_mgr.update("stream1", track_id=5, bbox=[100, 100, 200, 300])

    # Check helmet presence
    has_helmet = check_helmet_in_box(person_box, helmet_boxes)
    helmet_tracker.update("stream1", worker_id=5, has_helmet=has_helmet)

    # Blur faces for privacy
    if should_blur_person(label):
        blur_face_region(image, person_box)
"""

# Tracking utilities
from detection.common.tracking import TrackingManager, is_vehicle_moving

# Helmet detection utilities
from detection.common.helmet_detection import (
    HelmetTracker,
    is_person_box_large_enough,
    check_helmet_in_box,
    HELMET_TRACKING_WINDOW,
    HELMET_CONFIDENCE_THRESHOLD,
    MAX_MISSING_FRAMES,
    MIN_PERSON_BOX_WIDTH,
    MIN_PERSON_BOX_HEIGHT,
    MIN_PERSON_BOX_AREA,
    HELMET_DETECTION_OFFSET,
)

# Face blurring utilities
from detection.common.face_blurring import blur_face_region, should_blur_person


__all__ = [
    # Tracking
    "TrackingManager",
    "is_vehicle_moving",
    # Helmet detection
    "HelmetTracker",
    "is_person_box_large_enough",
    "check_helmet_in_box",
    "HELMET_TRACKING_WINDOW",
    "HELMET_CONFIDENCE_THRESHOLD",
    "MAX_MISSING_FRAMES",
    "MIN_PERSON_BOX_WIDTH",
    "MIN_PERSON_BOX_HEIGHT",
    "MIN_PERSON_BOX_AREA",
    "HELMET_DETECTION_OFFSET",
    # Face blurring
    "blur_face_region",
    "should_blur_person",
]
