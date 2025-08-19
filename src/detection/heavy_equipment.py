import cv2
import numpy as np
from typing import List, Tuple
from detection import draw_text_with_background
from ultralytics.engine.results import Results


CONFIDENCE_THRESHOLD = 0.4
DETECTION_COLOR = (255, 0, 255)
SAFE_COLOR = (0, 180, 0)
UNSAFE_COLOR = (0, 0, 255)
BOX_THICKNESS = 2
HELMET_DETECTION_OFFSET = 20

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
    16: "hook"
}


def draw_detection_box_and_label(
    image: np.ndarray, 
    coords: List[int], 
    label: str, 
    color: Tuple[int, int, int] = DETECTION_COLOR
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
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:
    """Detect heavy equipment and workers, check for helmet compliance.
    
    Args:
        image: Input image array
        results: YOLO detection results
        
    Returns:
        Tuple containing:
        - final_status: "Safe" or "UnSafe"
        - reasons: List of safety violations
        - bboxes: List of person bounding boxes
    """

    person_boxes: List[List[int]] = []
    hat_boxes: List[List[int]] = []
    final_status: str = "Safe"
    reasons: List[str] = []

    for result in results:
        for box in result.boxes.data:  # type: ignore
            coords = list(map(int, box[:4]))
            confidence = float(box[4])
            class_id = int(box[5])
            
            if confidence > CONFIDENCE_THRESHOLD:
                class_name = CLASS_NAMES.get(class_id, f"unknown_{class_id}")
                draw_detection_box_and_label(image, coords, class_name)
                
                if class_id == 10:  # worker
                    person_boxes.append(coords)
                elif class_id in [11, 12]:  # hard_hat or red_hard_hat
                    hat_boxes.append(coords)

    # Check helmet compliance for each worker
    for person_box in person_boxes:
        has_helmet = any(
            person_box[0] <= (hat_box[0] + hat_box[2]) / 2 < person_box[2]
            and hat_box[1] >= person_box[1] - HELMET_DETECTION_OFFSET
            for hat_box in hat_boxes
        )
        
        if has_helmet:
            draw_detection_box_and_label(
                image, person_box, "Worker with helmet", SAFE_COLOR
            )
        else:
            final_status = "UnSafe"
            reasons.append("missing_helmet")
            draw_detection_box_and_label(
                image, person_box, "Worker without helmet", UNSAFE_COLOR
            )

    reasons = list(set(reasons))

    person_bboxes: List[Tuple[int, int, int, int]] = [
        (box[0], box[1], box[2], box[3]) for box in person_boxes
    ]

    return final_status, reasons, person_bboxes
