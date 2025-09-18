import cv2
import numpy as np
import time
from boxmot import BotSort
import miniball
from pathlib import Path
import torch
from typing import List, Tuple, Dict
from detection import draw_text_with_background
from ultralytics.engine.results import Results
from config import FRAME_HEIGHT, FRAME_WIDTH


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
    0: "backhoe_loader",
    1: "cement_truck",
    2: "compactor",
    3: "dozer",
    4: "dump_truck",
    5: "excavator",
    6: "grader",
    7: "mobile_crane",
    8: "tower_crane",
    9: "wheel_loader",
    10: "worker",
    11: "hard_hat",
    12: "red_hard_hat",
    13: "scaffolding",
    14: "lifted_load",
    15: "crane_hook",
    16: "hook",
}

# Class name lists for proximity detection
CLS_NAMES = [
    "Backhoe loader",
    "Cement truck",
    "Compactor",
    "Dozer",
    "Dump truck",
    "Excavator",
    "Grader",
    "Mobile crane",
    "Tower crane",
    "Wheel loader",
    "Worker",
    "Hard hat",
    "Red hardhat",
    "Scaffolds",
    "Lifted load",
    "Crane hook",
    "Hook",
]

WORKER_CLASSES = ["worker"]

VEHICLE_CLASSES = [
    "backhoe_loader",
    "cement_truck",
    "compactor",
    "dozer",
    "dump_truck",
    "excavator",
    "grader",
    "mobile_crane",
    "tower_crane",
    "wheel_loader",
]

# Initialize tracker and homography matrix
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Global tracker instances per stream
_trackers = {}

# Helmet tracking system - stores helmet detection history for each worker
# Format: {stream_id: {worker_id: {'helmet_detections': [True/False], 'timestamps': [float]}}}
_helmet_tracking: Dict[str, Dict[int, Dict[str, List]]] = {}

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


def get_tracker(stream_id: str) -> BotSort:
    """Get or create a tracker instance for the given stream."""
    if stream_id not in _trackers:
        _trackers[stream_id] = BotSort(
            reid_weights=Path("osnet_x0_25_msmt17.pt"),  # Path to ReID model
            device=device,
            half=False,
            with_reid=False,
            track_buffer=150,
            cmc_method="sof",
            frame_rate=20,
            new_track_thresh=0.3,
        )
    return _trackers[stream_id]


def cleanup_tracker(stream_id: str) -> None:
    """Clean up tracker instance for the given stream."""
    if stream_id in _trackers:
        del _trackers[stream_id]
    if stream_id in _helmet_tracking:
        del _helmet_tracking[stream_id]


def update_helmet_tracking(stream_id: str, worker_id: int, has_helmet: bool) -> None:
    """Update helmet detection history for a worker."""
    current_time = time.time()

    if stream_id not in _helmet_tracking:
        _helmet_tracking[stream_id] = {}

    if worker_id not in _helmet_tracking[stream_id]:
        _helmet_tracking[stream_id][worker_id] = {
            "helmet_detections": [],
            "timestamps": [],
        }

    worker_history = _helmet_tracking[stream_id][worker_id]

    # Add current detection
    worker_history["helmet_detections"].append(has_helmet)
    worker_history["timestamps"].append(current_time)

    # Keep only recent detections within the tracking window
    if len(worker_history["helmet_detections"]) > HELMET_TRACKING_WINDOW:
        worker_history["helmet_detections"].pop(0)
        worker_history["timestamps"].pop(0)


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


def is_helmet_violation(stream_id: str, worker_id: int) -> bool:
    """Check if worker has a consistent helmet violation based on tracking history."""
    if (
        stream_id not in _helmet_tracking
        or worker_id not in _helmet_tracking[stream_id]
    ):
        return False

    worker_history = _helmet_tracking[stream_id][worker_id]
    detections = worker_history["helmet_detections"]

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


# Default homography transformation points
clicked_pts = [(500, 300), (700, 300), (750, 500), (560, 600)]
image_coords = np.float32(clicked_pts)
real_world_coords = np.float32([[0, 0], [2, 0], [2, 4.5], [0, 4.5]])
homography_matrix = cv2.getPerspectiveTransform(image_coords, real_world_coords)


def get_bottom_center(box):
    """Get bottom center point of bounding box."""
    x1, y1, x2, y2 = box
    return np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32)


def get_worker_center(box):
    """Get center point of worker bounding box."""
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)


def transform_to_world(pt):
    """Transform image coordinates to world coordinates."""
    return cv2.perspectiveTransform(pt, homography_matrix)[0][0]


def get_vehicle_ground_edges(box):
    """Get vehicle ground edge points for proximity calculation."""
    x1, y1, x2, y2 = box
    return [
        np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32),
        np.array([[[x1, y2]]], dtype=np.float32),
        np.array([[[x2, y2]]], dtype=np.float32),
    ]


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

    # Process all results, not just the first one
    all_detections = []
    for result in results:
        all_detections.extend(result.boxes.data.tolist())

    if not all_detections:
        return final_status, reasons, person_boxes

    worker_positions = []
    vehicle_positions = []
    scaffolding_positions = []
    Grab_crane_box, cran_arm_box, forklift_box = [], [], []
    worker_box, hat_box, signaler_box, scaffolding_box = [], [], [], []
    hook_box = []

    dets = []

    for detection in all_detections:
        x1, y1, x2, y2, conf, cls = detection
        cls_name = CLASS_NAMES.get(int(cls), f"unknown_{int(cls)}")
        box = [int(x1), int(y1), int(x2), int(y2)]

        # Tracking
        dets.append([*box, conf, cls])

    # Convert detections to numpy array (N X (x, y, x, y, conf, cls))
    dets = np.array(dets)

    # Get tracker for this stream and update it
    tracker = get_tracker(stream_id)
    tracker.update(dets, image)  # --> M X (x, y, x, y, id, conf, cls, ind)

    for trk in tracker.active_tracks:
        if not trk.history_observations:
            continue
        if len(trk.history_observations) < 3:
            continue
        cls_name = CLASS_NAMES.get(int(trk.cls), f"unknown_{int(trk.cls)}")
        box = [int(x) for x in trk.history_observations[-1]]
        if cls_name in VEHICLE_CLASSES:
            # Only draw vehicle boxes if not in violations-only mode
            if not draw_violations_only:
                cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
                draw_text_with_background(
                    image,
                    f"{cls_name}_id:{int(trk.id)}",
                    (box[0], box[1] - 10),
                    (0, 255, 0),
                )
            bottom_center = get_bottom_center(box)
            world_center = transform_to_world(bottom_center)
            vehicle_positions.append((world_center, trk))
            if cls_name == "Grab Crane":
                Grab_crane_box.append(box)
            elif cls_name == "Grab Crane Arm":
                cran_arm_box.append(box)
            elif cls_name == "Forklift":
                forklift_box.append(box)

        elif cls_name == "worker":
            worker_box.append(trk)
        elif cls_name == "hard_hat":
            hat_box.append(box)
            # Only draw helmet boxes if not in violations-only mode
            if not draw_violations_only:
                cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
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
                cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (0, 150, 0), 2)
                draw_text_with_background(
                    image, "Hook", (box[0], box[1] - 10), (0, 200, 0)
                )

    for w_box in worker_box:
        box = [int(x) for x in w_box.history_observations[-1]]
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
            update_helmet_tracking(stream_id, w_box.id, has_helmet)

            # Check if this worker has a consistent helmet violation
            has_helmet_violation = is_helmet_violation(stream_id, w_box.id)
        else:
            # Box too small for reliable helmet detection - skip helmet checking
            has_helmet = None  # Unknown helmet status
            has_helmet_violation = False  # Don't flag violations for small boxes

        add_id = f"_id:{w_box.id}"
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
            if enable_face_blurring and any(
                label.startswith(role) for role in ["Worker", "Driver", "Signaler"]
            ):
                x1, y1, x2, y2 = box
                blur_height = int(0.4 * (y2 - y1))
                y1_blur = y1
                y2_blur = y1 + blur_height

                if y2_blur > y1_blur and x2 > x1:
                    face_region = image[y1_blur:y2_blur, x1:x2]
                    if face_region.size > 0:
                        blurred = cv2.blur(face_region, (7, 7))
                        image[y1_blur:y2_blur, x1:x2] = blurred

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
    if scaffolding_box:
        # Check for vertical area violations (workers in same vertical space within scaffolding)
        vertical_groups = []

        # First, identify workers that are within scaffolding bounds
        workers_in_scaffolding = []
        for i, (_, w_box) in enumerate(worker_positions):
            for scaff_box in scaffolding_box:
                # Check if worker box is fully within scaffolding box
                if (
                    w_box[0] >= scaff_box[0]
                    and w_box[1] >= scaff_box[1]
                    and w_box[2] <= scaff_box[2]
                    and w_box[3] <= scaff_box[3]
                ):
                    workers_in_scaffolding.append(i)
                    break

        # Only check vertical area violations for workers within scaffolding
        for i in workers_in_scaffolding:
            for j in workers_in_scaffolding:
                if i != j:
                    w_box1 = worker_positions[i][1]
                    w_box2 = worker_positions[j][1]
                    # Check if workers are in same vertical area
                    if ((w_box1[1] + w_box1[3]) / 2) > w_box2[3] or (
                        (w_box2[1] + w_box2[3]) / 2
                    ) > w_box1[3]:
                        # Check horizontal overlap with expanded range
                        if (w_box1[0] - (w_box1[2] - w_box1[0]) / 2) < w_box2[2] and (
                            w_box1[2] + (w_box1[2] - w_box1[0]) / 2
                        ) > w_box2[0]:
                            # Find or create group for these workers
                            group_found = False
                            for group in vertical_groups:
                                if i in group or j in group:
                                    group.add(i)
                                    group.add(j)
                                    group_found = True
                                    break
                            if not group_found:
                                vertical_groups.append({i, j})

        if vertical_groups:
            final_status = "UnSafe"
            if "same_vertical_area" not in reasons:
                reasons.append("same_vertical_area")

            # Draw warning boxes around groups
            for group in vertical_groups:
                if len(group) > 1:
                    group_boxes = [worker_positions[i][1] for i in group]
                    min_x = min(box[0] for box in group_boxes)
                    min_y = min(box[1] for box in group_boxes)
                    max_x = max(box[2] for box in group_boxes)
                    max_y = max(box[3] for box in group_boxes)

                    padding = 20
                    min_x = max(0, min_x - padding)
                    min_y = max(0, min_y - padding)
                    max_x = min(FRAME_WIDTH, max_x + padding)
                    max_y = min(FRAME_HEIGHT, max_y + padding)

                    cv2.rectangle(image, (min_x, min_y), (max_x, max_y), (0, 0, 255), 4)
                    draw_text_with_background(
                        image,
                        "VERTICAL AREA VIOLATION",
                        (min_x, min_y - 10),
                        (0, 0, 255),
                    )

        # Check for missing hooks (safety harness connections) only for workers in scaffolding
        workers_in_scaffolding_count = len(workers_in_scaffolding)
        hook_count = len(hook_box)
        missing_hooks = max(0, workers_in_scaffolding_count - hook_count)

        if missing_hooks > 0:
            final_status = "UnSafe"
            if "missing_hook" not in reasons:
                reasons.append("missing_hook")

    # Vehicle proximity check (only when heavy vehicles are detected)
    vehicles_detected = len(vehicle_positions) > 0
    if vehicles_detected:
        for w_pt, w_box in worker_positions:
            for _, v_box in vehicle_positions:
                # check history:
                if len(v_box.history_observations) < 10:
                    continue

                centroids = np.array(
                    [
                        [int((x1 + x2) / 2), int((y1 + y2) / 2)]
                        for (x1, y1, x2, y2) in v_box.history_observations
                    ]
                )
                # Remove duplicates (recommended)
                centroids = np.unique(centroids, axis=0)
                # Compute the minimum enclosing ball
                center, radius_squared = miniball.get_bounding_ball(centroids)
                radius = radius_squared**0.5

                if radius < VEHICLE_MOVING_THRESH:
                    continue
                v_box1 = [int(x) for x in v_box.history_observations[-1]]
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
