import cv2
import numpy as np
from typing import List, Tuple
from detection import draw_text_with_background
from ultralytics.engine.results import Results


def detect_heavy_equipment(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:

    person_boxes: List[List[int]] = []
    hat_boxes: List[List[int]] = []
    final_status: str = "Safe"
    reasons: List[str] = []

    for result in results:
        for box in result.boxes.data:  # type: ignore
            coords = list(map(int, box[:4]))
            confi = float(box[4])
            clas = int(box[5])
            if confi > 0.4:
                cv2.rectangle(
                    image,
                    (coords[0], coords[1]),
                    (coords[2], coords[3]),
                    (255, 0, 255),
                    2,
                )
                if clas == 0:
                    draw_text_with_background(
                        image,
                        "backhoe_loader",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 1:
                    draw_text_with_background(
                        image,
                        "cement_truck",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 2:
                    draw_text_with_background(
                        image,
                        "compactor",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 3:
                    draw_text_with_background(
                        image,
                        "dozer",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 4:
                    draw_text_with_background(
                        image,
                        "dump_truck",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 5:
                    draw_text_with_background(
                        image,
                        "excavator",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 6:
                    draw_text_with_background(
                        image,
                        "grader",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 7:
                    draw_text_with_background(
                        image,
                        "mobile_crane",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 8:
                    draw_text_with_background(
                        image,
                        "tower_crane",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 9:
                    draw_text_with_background(
                        image,
                        "wheel_loader",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 10:
                    draw_text_with_background(
                        image,
                        "worker",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                    person_boxes.append(coords)
                elif clas == 11:
                    draw_text_with_background(
                        image,
                        "hard_hat",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                    hat_boxes.append(coords)
                elif clas == 12:
                    draw_text_with_background(
                        image,
                        "red_hard_hat",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                    hat_boxes.append(coords)
                elif clas == 13:
                    draw_text_with_background(
                        image,
                        "scaffolding",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 14:
                    draw_text_with_background(
                        image,
                        "lifted_load",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 15:
                    draw_text_with_background(
                        image,
                        "crane_hook",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )
                elif clas == 16:
                    draw_text_with_background(
                        image,
                        "hook",
                        (coords[0], coords[1] - 10),
                        (255, 0, 255),
                    )

    # hard hat detection logic
    for perBox in person_boxes:
        hatDetected = any(
            perBox[0] <= (hatBox[0] + hatBox[2]) / 2 < perBox[2]
            and hatBox[1] >= perBox[1] - 20
            for hatBox in hat_boxes
        )
        if hatDetected:
            cv2.rectangle(
                image,
                (perBox[0], perBox[1]),
                (perBox[2], perBox[3]),
                (0, 180, 0),
                2,
            )
            draw_text_with_background(
                image,
                "Worker with helmet",
                (perBox[0], perBox[1] - 10),
                (0, 180, 0),
            )
        else:
            final_status = "UnSafe"
            reasons.append("missing_helmet")
            cv2.rectangle(
                image,
                (perBox[0], perBox[1]),
                (perBox[2], perBox[3]),
                (0, 0, 255),
                2,
            )
            draw_text_with_background(
                image,
                "Worker without helmet",
                (perBox[0], perBox[1] - 10),
                (0, 0, 255),
            )

    reasons = list(set(reasons))

    bboxes: List[Tuple[int, int, int, int]] = [
        (box[0], box[1], box[2], box[3]) for box in person_boxes
    ]

    return final_status, reasons, bboxes
