import cv2
import numpy as np
from typing import List, Tuple
from detection import draw_text_with_background
from ultralytics.engine.results import Results


def detect_ppe(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:

    person_boxes: List[List[int]] = []
    hat_boxes: List[List[int]] = []
    final_status: str = "Safe"
    reasons: List[str] = []

    # Get image dimensions to scale the font and other elements accordingly
    img_height, img_width = image.shape[:2]
    font_scale = 1  # max(0.2, img_width / 1000)
    thickness = max(1, int(img_width / 500))

    for result in results:
        for box in result.boxes.data:  # type: ignore
            coords = list(map(int, box[:4]))
            confi = float(box[4])
            clas = int(box[5])
            if confi > 0.6:
                if clas == 1:
                    cv2.rectangle(
                        image,
                        (coords[0], coords[1]),
                        (coords[2], coords[3]),
                        (0, 255, 0),
                        2,
                    )
                    # self.draw_text_with_background(image, f"Hard Hat", (coords[0], coords[1] - 10), font_scale, (0, 255, 0), thickness)
                    hat_boxes.append(coords)
                elif clas == 2:
                    person_boxes.append(coords)

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
                font_scale,
                (0, 180, 0),
                thickness,
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
                font_scale,
                (0, 0, 255),
                thickness,
            )

    color_status = (0, 0, 255) if final_status == "UnSafe" else (0, 255, 0)
    draw_text_with_background(
        image, final_status, (40, 50 - 10), font_scale, color_status, thickness
    )
    # cv2.putText(image, final_status, (40, 50), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color_status, thickness)

    # Adding reasons for unsafe behavior if any
    if reasons:
        for idx, reason in enumerate(reasons):
            draw_text_with_background(
                image,
                reason,
                (40, 100 + (idx * 30)),
                font_scale,
                (0, 0, 255),
                thickness,
            )

    bboxes: List[Tuple[int, int, int, int]] = [
        (box[0], box[1], box[2], box[3]) for box in person_boxes
    ]

    return final_status, reasons, bboxes
