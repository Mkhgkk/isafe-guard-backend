import cv2
import numpy as np
import time
from typing import List, Tuple, Dict
from collections import deque
from detection import draw_text_with_background
from ultralytics.engine.results import Results


# Detection constants
CONFIDENCE_THRESHOLD = 0.6
SAFE_COLOR = (0, 180, 0)
UNSAFE_COLOR = (0, 0, 255)
HELMET_COLOR = (255, 0, 255)
BOX_THICKNESS = 2

# Helmet tracking system - stores helmet detection history for each person
# Format: {stream_id: {person_id: {'helmet_detections': [True/False], 'timestamps': [float]}}}
_helmet_tracking: Dict[str, Dict[int, Dict[str, List]]] = {}

# Global tracking history per stream
# Format: {stream_id: {track_id: deque([bbox1, bbox2, ...])}}
_track_history: Dict[str, Dict[int, deque]] = {}

# Helmet tracking constants
HELMET_TRACKING_WINDOW = 90  # Number of recent frames to consider
HELMET_CONFIDENCE_THRESHOLD = (
    0.7  # Ratio of frames with helmet needed to be considered "safe"
)
MAX_MISSING_FRAMES = (
    5  # Allow up to 5 consecutive frames without detection before considering violation
)

# Minimum person box size for reliable helmet detection
MIN_PERSON_BOX_WIDTH = 30  # Minimum width in pixels
MIN_PERSON_BOX_HEIGHT = 60  # Minimum height in pixels
MIN_PERSON_BOX_AREA = MIN_PERSON_BOX_WIDTH * MIN_PERSON_BOX_HEIGHT


def update_track_history(stream_id: str, track_id: int, bbox: List[int]) -> None:
    """Update tracking history for a tracked object."""
    if stream_id not in _track_history:
        _track_history[stream_id] = {}

    if track_id not in _track_history[stream_id]:
        _track_history[stream_id][track_id] = deque(maxlen=30)  # Keep last 30 frames

    _track_history[stream_id][track_id].append(bbox)


def get_track_history(stream_id: str, track_id: int) -> deque:
    """Get tracking history for a specific track."""
    if stream_id in _track_history and track_id in _track_history[stream_id]:
        return _track_history[stream_id][track_id]
    return deque()


def cleanup_tracker(stream_id: str) -> None:
    """Clean up tracking data for the given stream."""
    if stream_id in _track_history:
        del _track_history[stream_id]
    if stream_id in _helmet_tracking:
        del _helmet_tracking[stream_id]


def update_helmet_tracking(stream_id: str, person_id: int, has_helmet: bool) -> None:
    """Update helmet detection history for a person."""
    current_time = time.time()

    if stream_id not in _helmet_tracking:
        _helmet_tracking[stream_id] = {}

    if person_id not in _helmet_tracking[stream_id]:
        _helmet_tracking[stream_id][person_id] = {
            "helmet_detections": [],
            "timestamps": [],
        }

    person_history = _helmet_tracking[stream_id][person_id]

    # Add current detection
    person_history["helmet_detections"].append(has_helmet)
    person_history["timestamps"].append(current_time)

    # Keep only recent detections within the tracking window
    if len(person_history["helmet_detections"]) > HELMET_TRACKING_WINDOW:
        person_history["helmet_detections"].pop(0)
        person_history["timestamps"].pop(0)


def is_person_box_large_enough(box: List[int]) -> bool:
    """Check if person bounding box is large enough for reliable helmet detection."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    area = width * height

    return (
        width >= MIN_PERSON_BOX_WIDTH
        and height >= MIN_PERSON_BOX_HEIGHT
        and area >= MIN_PERSON_BOX_AREA
    )


def is_helmet_violation(stream_id: str, person_id: int) -> bool:
    """Check if person has a consistent helmet violation based on tracking history."""
    if (
        stream_id not in _helmet_tracking
        or person_id not in _helmet_tracking[stream_id]
    ):
        return False

    person_history = _helmet_tracking[stream_id][person_id]
    detections = person_history["helmet_detections"]

    if len(detections) < MAX_MISSING_FRAMES:
        return False  # Not enough data yet

    # Calculate recent helmet detection rate
    recent_detections = (
        detections[-HELMET_TRACKING_WINDOW:]
        if len(detections) >= HELMET_TRACKING_WINDOW
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
    return (
        helmet_rate < HELMET_CONFIDENCE_THRESHOLD
        and consecutive_missing >= MAX_MISSING_FRAMES
    )


def detect_approtium(
    image: np.ndarray,
    results: List[Results],
    stream_id: str = "default",
    draw_violations_only: bool = False,
    enable_face_blurring: bool = False,
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:
    """Detect approtium workers and helmet compliance with person tracking.

    Args:
        image: Input image array
        results: YOLO detection results
        stream_id: Stream identifier for tracking
        draw_violations_only: If True, only draw boxes for violations and unsafe conditions.
                              If False, draw all detection boxes (default behavior).
        enable_face_blurring: If True, blur faces for privacy (default: True).

    Returns:
        Tuple containing:
        - final_status: "Safe" or "UnSafe"
        - reasons: List of safety violations
        - bboxes: List of person bounding boxes
    """

    person_boxes_with_tracking: List[Tuple[int, List[int]]] = []  # (track_id, box)
    hat_boxes: List[List[int]] = []
    final_status: str = "Safe"
    reasons: List[str] = []

    # Process YOLO tracking results (track IDs are already assigned by YOLO)
    for result in results:
        if result.boxes is None or len(result.boxes) == 0:
            continue

        boxes = result.boxes
        # Check if tracking IDs are available
        has_track_ids = boxes.id is not None

        for idx, box_data in enumerate(boxes.data):
            box_list = box_data.tolist()

            # Handle both detection and tracking formats
            # Detection format: [x1, y1, x2, y2, conf, cls]
            # Tracking format: [x1, y1, x2, y2, track_id, conf, cls] or similar
            if len(box_list) == 6:
                x1, y1, x2, y2, conf, cls = box_list
                # Get track ID from boxes.id if available
                track_id = int(boxes.id[idx].item()) if (has_track_ids and boxes.id is not None) else -1
            elif len(box_list) == 7:
                # Track format with ID in data
                x1, y1, x2, y2, track_id_data, conf, cls = box_list
                track_id = int(track_id_data)
            else:
                # Fallback for unexpected formats
                x1, y1, x2, y2 = box_list[:4]
                conf = box_list[-2] if len(box_list) >= 6 else 0.5
                cls = box_list[-1] if len(box_list) >= 5 else 0
                track_id = int(boxes.id[idx].item()) if (has_track_ids and boxes.id is not None) else -1

            coords = [int(x1), int(y1), int(x2), int(y2)]
            clas = int(cls)

            # Update tracking history for this object
            if track_id >= 0:
                update_track_history(stream_id, track_id, coords)

            # Get tracking history
            history = (
                get_track_history(stream_id, track_id) if track_id >= 0 else deque()
            )

            # Skip objects with insufficient tracking history
            if track_id >= 0 and len(history) < 3:
                continue

            if conf > CONFIDENCE_THRESHOLD:
                # Class 1: White helmet
                if clas == 1:
                    hat_boxes.append(coords)
                    # Only draw helmet boxes if not in violations-only mode
                    if not draw_violations_only:
                        cv2.rectangle(
                            image,
                            (coords[0], coords[1]),
                            (coords[2], coords[3]),
                            (255, 255, 255),  # White color for white helmet
                            BOX_THICKNESS,
                        )
                # Class 2: Yellow helmet
                elif clas == 2:
                    hat_boxes.append(coords)
                    # Only draw helmet boxes if not in violations-only mode
                    if not draw_violations_only:
                        cv2.rectangle(
                            image,
                            (coords[0], coords[1]),
                            (coords[2], coords[3]),
                            (0, 255, 255),  # Yellow color for yellow helmet
                            BOX_THICKNESS,
                        )
                # Class 0: Person
                elif clas == 0:
                    # Store person with track_id and box
                    person_boxes_with_tracking.append((track_id, coords))

    # Process each tracked person
    person_bboxes: List[Tuple[int, int, int, int]] = []

    for person_track_id, perBox in person_boxes_with_tracking:
        # Check if person box is large enough for reliable helmet detection
        box_large_enough = is_person_box_large_enough(perBox)

        if box_large_enough:
            # Check for helmet detection in current frame
            has_helmet = any(
                perBox[0] <= (hatBox[0] + hatBox[2]) / 2 < perBox[2]
                and hatBox[1] >= perBox[1] - 20
                for hatBox in hat_boxes
            )

            # Update helmet tracking for this person
            update_helmet_tracking(stream_id, person_track_id, has_helmet)

            # Check if this person has a consistent helmet violation
            has_helmet_violation = is_helmet_violation(stream_id, person_track_id)
        else:
            # Box too small for reliable helmet detection - skip helmet checking
            has_helmet = None  # Unknown helmet status
            has_helmet_violation = False  # Don't flag violations for small boxes

        # Determine label and color based on helmet status
        add_id = f"_id:{person_track_id}"
        if not box_large_enough:
            label = "Person (too distant)" + add_id
            color = (128, 128, 128)  # Gray color for too small/distant
        elif has_helmet_violation:
            label = "Person without helmet" + add_id
            color = UNSAFE_COLOR
            final_status = "UnSafe"
            if "missing_helmet" not in reasons:
                reasons.append("missing_helmet")
        elif has_helmet:
            label = "Person with helmet" + add_id
            color = SAFE_COLOR
        else:
            # Temporary no helmet detection - checking status
            label = "Person (helmet checking...)" + add_id
            color = (0, 165, 255)  # Orange color for uncertain status

        # Determine if this person should be drawn based on violation status
        has_violation = (
            "without helmet" in label
            or "too distant" in label
            or "helmet checking..." in label
        )
        should_draw = not draw_violations_only or has_violation

        if should_draw:
            # Face blurring for privacy (top 40%)
            if enable_face_blurring and "Person" in label:
                x1, y1, x2, y2 = perBox
                blur_height = int(0.4 * (y2 - y1))
                y1_blur = y1
                y2_blur = y1 + blur_height

                if y2_blur > y1_blur and x2 > x1:
                    face_region = image[y1_blur:y2_blur, x1:x2]
                    if face_region.size > 0:
                        blurred = cv2.blur(face_region, (7, 7))
                        image[y1_blur:y2_blur, x1:x2] = blurred

            # Draw bounding box and label
            cv2.rectangle(
                image,
                (perBox[0], perBox[1]),
                (perBox[2], perBox[3]),
                color,
                BOX_THICKNESS,
            )
            draw_text_with_background(
                image,
                label,
                (perBox[0], perBox[1] - 10),
                color,
            )

        # Add to person boxes for return value
        person_bboxes.append((perBox[0], perBox[1], perBox[2], perBox[3]))

    # Ensure reasons are unique
    reasons = list(set(reasons))

    return final_status, reasons, person_bboxes
