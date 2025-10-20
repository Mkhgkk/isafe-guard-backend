import cv2
import math
import numpy as np
from typing import List, Tuple, Optional
from detection import draw_text_with_background
from ultralytics.engine.results import Results


# Configuration constants
DIST_THRESH = 2.5  # Distance threshold in meters
PPM = 175 / 2  # Pixels per meter: 175px ~ 2m
CONFIDENCE_THRESHOLD = 0.4

# Class names and IDs
CLASS_NAMES = {
    0: "forklift",
    1: "worker"
}

# Colors (BGR format)
COLOR_SAFE = (0, 255, 0)  # Green
COLOR_WORKER = (255, 0, 0)  # Blue
COLOR_DANGER = (0, 0, 255)  # Red


def euclidean_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
    """Calculate Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)


def detect_nexilis_proximity(
    image: np.ndarray,
    results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:
    """
    Detect proximity violations between workers and forklifts.

    This detector implements the Nexilis proximity checking algorithm that:
    1. Detects workers and forklifts
    2. Calculates distances between workers and forklifts
    3. Flags violations when workers are too close to forklifts

    Args:
        image: Input image frame (numpy array)
        results: YOLO detection results

    Returns:
        Tuple of (status, reasons, person_boxes):
        - status: "Safe" or "UnSafe"
        - reasons: List of violation reasons (e.g., ["proximity_violation"])
        - person_boxes: List of detected worker bounding boxes
    """

    final_status = "Safe"
    reasons: List[str] = []
    person_boxes: List[Tuple[int, int, int, int]] = []

    imgH, imgW = image.shape[:2]

    # Collect all detections from results
    worker_boxes = []
    forklift_boxes = []

    for result in results:
        for box in result.boxes.data:
            x1, y1, x2, y2, conf, cls = box
            conf = float(conf)
            cls = int(cls)

            # Filter by confidence threshold
            if conf < CONFIDENCE_THRESHOLD:
                continue

            # Convert to integer coordinates
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            box_coords = (x1, y1, x2, y2)

            cls_name = CLASS_NAMES.get(cls, f"unknown_{cls}")

            if cls_name == "worker":
                worker_boxes.append(box_coords)
            elif cls_name == "forklift":
                forklift_boxes.append(box_coords)

    # Draw forklift boxes first
    for forklift_box in forklift_boxes:
        x1, y1, x2, y2 = forklift_box
        cv2.rectangle(image, (x1, y1), (x2, y2), COLOR_SAFE, 2)
        draw_text_with_background(
            image,
            "forklift",
            (x1, y1 - 10),
            COLOR_SAFE
        )

    # Process each worker
    for worker_box in worker_boxes:
        x1_w, y1_w, x2_w, y2_w = worker_box

        # Calculate bottom center of worker box
        worker_btm_center = ((x1_w + x2_w) // 2, y2_w)

        in_danger = False

        # Check distance to each forklift
        for forklift_box in forklift_boxes:
            x1_f, y1_f, x2_f, y2_f = forklift_box

            # Calculate bottom center of forklift box
            forklift_btm_center = ((x1_f + x2_f) // 2, y2_f)

            # Calculate distance in pixels
            dist_pixels = euclidean_distance(worker_btm_center, forklift_btm_center)

            # Convert to meters
            dist_meters = dist_pixels / PPM

            # Check if worker is in danger zone
            if dist_meters < DIST_THRESH:
                in_danger = True
                line_color = COLOR_DANGER
            else:
                line_color = COLOR_SAFE

            # Draw line between worker and forklift
            cv2.line(image, worker_btm_center, forklift_btm_center, line_color, 2)

            # Draw distance label at midpoint
            mid_x = (worker_btm_center[0] + forklift_btm_center[0]) // 2
            mid_y = (worker_btm_center[1] + forklift_btm_center[1]) // 2

            draw_text_with_background(
                image,
                f"{dist_meters:.2f} m",
                (mid_x, mid_y),
                COLOR_SAFE
            )

        # Determine worker box color based on danger status
        if in_danger:
            box_color = COLOR_DANGER
            label = "worker"
            final_status = "UnSafe"
            if "proximity_violation" not in reasons:
                reasons.append("proximity_violation")
        else:
            box_color = COLOR_WORKER
            label = "worker"

        # Draw worker box and label
        cv2.rectangle(image, (x1_w, y1_w), (x2_w, y2_w), box_color, 2)
        draw_text_with_background(
            image,
            label,
            (x1_w, y1_w - 10),
            box_color
        )

        # Add to person boxes list
        person_boxes.append((x1_w, y1_w, x2_w, y2_w))

    return final_status, reasons, person_boxes
