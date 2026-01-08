import cv2
import numpy as np
import time
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from collections import deque
from detection import draw_text_with_background
from ultralytics.engine.results import Results
from config import FRAME_HEIGHT, FRAME_WIDTH

# Import common modules
from detection.common.tracking import TrackingManager, is_vehicle_moving
from detection.common.helmet_detection import (
    HelmetTracker,
    is_person_box_large_enough,
    HELMET_TRACKING_WINDOW,
    HELMET_CONFIDENCE_THRESHOLD,
    MAX_MISSING_FRAMES,
    MIN_PERSON_BOX_WIDTH,
    MIN_PERSON_BOX_HEIGHT,
    MIN_PERSON_BOX_AREA,
)
from detection.common.face_blurring import blur_face_region, should_blur_person
from detection.common.geometry import (
    get_bottom_center,
    get_worker_center,
    transform_to_world,
    get_vehicle_ground_edges,
)
from detection.common.scaffold_utils import (
    process_scaffolding_safety,
)

# Constants
CONFIDENCE_THRESHOLD = 0.4
DETECTION_COLOR = (255, 0, 255)
SAFE_COLOR = (0, 180, 0)
UNSAFE_COLOR = (0, 0, 255)
BOX_THICKNESS = 2
HELMET_DETECTION_OFFSET = 20

# Proximity detection constants
DANGER_DIST_METERS = 2  # in meters
VEHICLE_MOVING_THRESH = 10

CLASS_NAMES = {
    0: "cement_truck",
    1: "compactor",
    2: "dump_truck",
    3: "excavator",
    4: "grader",
    5: "mobile_crane",
    6: "tower_crane",
    7: "crane_hook",
    8: "worker",
    9: "hard_hat",
    10: "red_hard_hat",
    11: "scaffolding",
    12: "lifted_load",
    13: "hook",
}

# Class name lists for proximity detection
CLS_NAMES = [
    "Cement truck",
    "Compactor",
    "Dump truck",
    "Excavator",
    "Grader",
    "Mobile crane",
    "Tower crane",
    "Crane hook",
    "Worker",
    "Hard hat",
    "Red hardhat",
    "Scaffolds",
    "Lifted load",
    "Hook",
]

WORKER_CLASSES = ["worker"]

VEHICLE_CLASSES = [
    # "backhoe_loader",
    "cement_truck",
    "compactor",
    # "dozer",
    "dump_truck",
    "excavator",
    "grader",
    "mobile_crane",
    "tower_crane",
    # "wheel_loader",
]

TRACKABLE_CLASSES = set(VEHICLE_CLASSES + WORKER_CLASSES)

# Initialize global managers
tracking_manager = TrackingManager()
helmet_tracker = HelmetTracker()

def cleanup_tracker(stream_id: str) -> None:
    """Clean up tracking data for the given stream."""
    tracking_manager.cleanup(stream_id)
    helmet_tracker.cleanup(stream_id)

def draw_detection_box_and_label(
    image: np.ndarray,
    coords: List[int],
    label: str,
    color: Tuple[int, int, int] = DETECTION_COLOR,
) -> None:
    """Draw detection box and label on image."""
    cv2.rectangle(
        image,
        (coords[0], coords[1]),
        (coords[2], coords[3]),
        color,
        BOX_THICKNESS,
    )
    draw_text_with_background(
        image,
        label,
        (coords[0], coords[1] - 10),
        color,
    )

def detect_heavy_equipment(
    image: np.ndarray,
    results: List[Results],
    stream_id: str = "default",
    draw_violations_only: bool = False,
    enable_face_blurring: bool = True,
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:
    """Detect heavy equipment and workers with proximity and helmet compliance checks.

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

    final_status = "Safe"
    reasons: List[str] = []
    person_boxes: List[Tuple[int, int, int, int]] = []

    worker_positions = []
    vehicle_positions = []
    scaffolding_positions = []
    Grab_crane_box, cran_arm_box, forklift_box = [], [], []
    worker_box, hat_box, signaler_box, scaffolding_box = [], [], [], []
    hook_box = []

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
            if len(box_list) == 6:
                x1, y1, x2, y2, conf, cls = box_list
                track_id = int(boxes.id[idx].item()) if has_track_ids else -1
            elif len(box_list) == 7:
                x1, y1, x2, y2, track_id_data, conf, cls = box_list
                track_id = int(track_id_data)
            else:
                x1, y1, x2, y2 = box_list[:4]
                conf = box_list[-2] if len(box_list) >= 6 else 0.5
                cls = box_list[-1] if len(box_list) >= 5 else 0
                track_id = int(boxes.id[idx].item()) if has_track_ids else -1

            cls_name = CLASS_NAMES.get(int(cls), f"unknown_{int(cls)}")
            box = [int(x1), int(y1), int(x2), int(y2)]

            # Only track specific classes to save resources
            is_trackable = cls_name in TRACKABLE_CLASSES
            
            if is_trackable and track_id >= 0:
                tracking_manager.update(stream_id, track_id, box)

            # Get tracking history for movement detection if applicable
            history = (
                tracking_manager.get_history(stream_id, track_id) 
                if is_trackable and track_id >= 0 
                else deque()
            )

            # For trackable objects, require minimum history to reduce noise
            # For non-trackable objects (like scaffolding), process immediately
            if is_trackable and track_id >= 0 and len(history) < 3:
                continue

            if cls_name in VEHICLE_CLASSES:
                # Only draw vehicle boxes if not in violations-only mode
                if not draw_violations_only:
                    cv2.rectangle(
                        image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2
                    )
                    draw_text_with_background(
                        image,
                        f"{cls_name}_id:{track_id}",
                        (box[0], box[1] - 10),
                        (0, 255, 0),
                    )
                bottom_center = get_bottom_center(box)
                world_center = transform_to_world(bottom_center)
                # Store vehicle position with track_id and history
                vehicle_positions.append((world_center, track_id, history))
                if cls_name == "Grab Crane":
                    Grab_crane_box.append(box)
                elif cls_name == "Grab Crane Arm":
                    cran_arm_box.append(box)
                elif cls_name == "Forklift":
                    forklift_box.append(box)

            elif cls_name == "worker":
                # Store worker with track_id and box
                worker_box.append((track_id, box))
            elif cls_name == "hard_hat":
                hat_box.append(box)
                # Only draw helmet boxes if not in violations-only mode
                if not draw_violations_only:
                    cv2.rectangle(
                        image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2
                    )
            elif cls_name == "red_hard_hat":
                signaler_box.append(box)
                # Only draw signaler helmet boxes if not in violations-only mode
                if not draw_violations_only:
                    cv2.rectangle(
                        image, (box[0], box[1]), (box[2], box[3]), (255, 255, 0), 2
                    )
            elif cls_name == "scaffolding":
                scaffolding_box.append(box)
                # Only draw scaffolding boxes if not in violations-only mode
                if not draw_violations_only:
                    cv2.rectangle(
                        image, (box[0], box[1]), (box[2], box[3]), (128, 128, 0), 2
                    )
                    draw_text_with_background(
                        image, "Scaffolding", (box[0], box[1] - 10), (128, 128, 0)
                    )
            elif cls_name == "hook":
                hook_box.append(box)
                # Only draw hook boxes if not in violations-only mode
                if not draw_violations_only:
                    cv2.rectangle(
                        image, (box[0], box[1]), (box[2], box[3]), (0, 150, 0), 2
                    )
                    draw_text_with_background(
                        image, "Hook", (box[0], box[1] - 10), (0, 200, 0)
                    )

    for worker_track_id, box in worker_box:
        center = get_worker_center(box)

        label = None
        color = (0, 255, 0)

        is_signaler = any(
            box[0] <= (sBox[0] + sBox[2]) / 2 < box[2] and sBox[1] >= box[1] - 20
            for sBox in signaler_box
        )

        is_driver = any(
            ca_box[1] - 50 < center[1] < ca_box[3] + 50 for ca_box in cran_arm_box
        ) or any(
            (center[1] < (g_box[1] + g_box[3]) / 2) or (g_box[3] > box[1])
            for g_box in Grab_crane_box
        )

        # Check if person box is large enough for reliable helmet detection
        box_large_enough = is_person_box_large_enough(box)

        if box_large_enough:
            has_helmet = any(
                box[0] <= (hatBox[0] + hatBox[2]) / 2 < box[2]
                and hatBox[1] >= box[1] - 20
                for hatBox in hat_box
            )

            # Update helmet tracking for this worker
            helmet_tracker.update(stream_id, worker_track_id, has_helmet)

            # Check if this worker has a consistent helmet violation
            has_helmet_violation = helmet_tracker.is_violation(stream_id, worker_track_id)
        else:
            # Box too small for reliable helmet detection - skip helmet checking
            has_helmet = None  # Unknown helmet status
            has_helmet_violation = False  # Don't flag violations for small boxes

        add_id = f"_id:{worker_track_id}"
        if is_signaler:
            label = "Signaler" + add_id
            color = (255, 255, 0)
        elif is_driver:
            if not box_large_enough:
                label = "Driver (too distant)" + add_id
                color = (128, 128, 128)  # Gray color for too small/distant
            elif has_helmet_violation:
                # Double-check if driver is actually too distant before flagging helmet violation
                if not box_large_enough:
                    label = "Driver (too distant for helmet detection)" + add_id
                    color = (128, 128, 128)  # Gray color for too small/distant
                else:
                    label = "Driver without helmet" + add_id
                    color = (0, 0, 255)
            elif has_helmet:
                label = "Driver with helmet" + add_id
                color = (0, 180, 255)
            else:
                # Temporary no helmet detection - check if it's due to distance
                if not box_large_enough:
                    label = "Driver (too distant for helmet detection)" + add_id
                    color = (128, 128, 128)  # Gray color for too small/distant
                else:
                    label = "Driver (helmet checking...)" + add_id
                    color = (0, 165, 255)  # Orange color for uncertain status
        else:
            if not box_large_enough:
                label = "Worker (too distant)" + add_id
                color = (128, 128, 128)  # Gray color for too small/distant
            elif has_helmet_violation:
                # Double-check if worker is actually too distant before flagging helmet violation
                if not box_large_enough:
                    label = "Worker (too distant for helmet detection)" + add_id
                    color = (128, 128, 128)  # Gray color for too small/distant
                else:
                    label = "Worker without helmet" + add_id
                    color = (0, 0, 255)
            elif has_helmet:
                label = "Worker with helmet" + add_id
                color = (0, 180, 0)
            else:
                # Temporary no helmet detection - check if it's due to distance
                if not box_large_enough:
                    label = "Worker (too distant for helmet detection)" + add_id
                    color = (128, 128, 128)  # Gray color for too small/distant
                else:
                    label = "Worker (helmet checking...)" + add_id
                    color = (0, 165, 255)  # Orange color for uncertain status

        # Determine if this worker should be drawn based on violation status
        has_violation = (
            "without helmet" in label
            or "too distant" in label
            or "helmet checking..." in label
        )
        should_draw = not draw_violations_only or has_violation

        if should_draw:
            # Face blurring for privacy (top 40%)
            if enable_face_blurring and should_blur_person(label):
                blur_face_region(image, box)

            # Draw label and box
            cv2.rectangle(
                image, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, 2
            )
            draw_text_with_background(
                image, label, (int(box[0]), int(box[1]) - 10), color
            )

        if any(
            keyword in label
            for keyword in [
                "Worker with helmet",
                "Worker without helmet",
                "Worker (helmet checking...",
                "Worker (too distant)",
            ]
        ):
            bottom_center = get_bottom_center(box)
            world_center = transform_to_world(bottom_center)
            worker_positions.append((world_center, box))

            # Add to person_boxes for return value
            person_boxes.append((int(box[0]), int(box[1]), int(box[2]), int(box[3])))

            # Add safety violations to reasons based on helmet tracking
            # Only flag helmet violations if worker is close enough for reliable detection
            if has_helmet_violation and box_large_enough:
                if "missing_helmet" not in reasons:
                    reasons.append("missing_helmet")
                final_status = "UnSafe"

    # Scaffolding safety checks (when scaffolding is detected)
    is_scaffold_unsafe, scaffold_reasons = process_scaffolding_safety(
        image,
        scaffolding_box,
        worker_positions,
        hook_box,
        FRAME_WIDTH,
        FRAME_HEIGHT
    )
    
    if is_scaffold_unsafe:
        final_status = "UnSafe"
        reasons.extend(scaffold_reasons)

    # Vehicle proximity check (only when heavy vehicles are detected)
    vehicles_detected = len(vehicle_positions) > 0
    if vehicles_detected:
        for w_pt, w_box in worker_positions:
            for _, v_track_id, v_history in vehicle_positions:
                # Check if vehicle has enough tracking history
                if len(v_history) < 10:
                    continue

                # Check if vehicle is moving using displacement calculation
                if not is_vehicle_moving(v_history):
                    continue

                # Get current vehicle box from history
                v_box1 = list(v_history[-1])
                vehicle_candidates = get_vehicle_ground_edges(v_box1)
                vehicle_world_pts = [transform_to_world(p) for p in vehicle_candidates]
                closest_v_pt = min(
                    vehicle_world_pts, key=lambda p: float(np.linalg.norm(p - w_pt))
                )

                dist = np.linalg.norm(w_pt - closest_v_pt)
                color = (0, 0, 255) if dist < DANGER_DIST_METERS else (0, 255, 0)

                is_violation = dist < DANGER_DIST_METERS

                if is_violation:
                    draw_text_with_background(
                        image,
                        f"ALERT: {dist:.2f}m",
                        (int(w_box[0]), int(w_box[1]) - 30),
                        (0, 0, 255),
                    )
                    # Add proximity violation to reasons
                    if "proximity_violation" not in reasons:
                        reasons.append("proximity_violation")
                    final_status = "UnSafe"

                # Draw proximity lines and distance labels
                # Always draw violations, conditionally draw safe distances
                if not draw_violations_only or is_violation:
                    pt1 = (int((w_box[0] + w_box[2]) // 2), int(w_box[3]))
                    pt2 = (int((v_box1[0] + v_box1[2]) // 2), int(v_box1[3]))
                    cv2.line(image, pt1, pt2, color, 2)
                    draw_text_with_background(
                        image,
                        f"{dist:.2f}m",
                        ((int(pt1[0]) + pt2[0]) // 2, (pt1[1] + pt2[1]) // 2),
                        color,
                    )

    # Ensure reasons are unique
    reasons = list(set(reasons))

    return final_status, reasons, person_boxes
