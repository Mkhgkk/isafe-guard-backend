import cv2
import numpy as np
from typing import List, Optional, Tuple
from ultralytics.engine.results import Results


def detect_fire_smoke(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:

    final_status = "Safe"
    reason = set()

    for result in results:
        for box in result.boxes.data:  # type: ignore
            coords = list(map(int, box[:4]))
            confi = float(box[4])
            clas = int(box[5])
            if confi > 0.4:
                if clas == 0:
                    cv2.rectangle(
                        image,
                        (coords[0], coords[1]),
                        (coords[2], coords[3]),
                        (0, 0, 255),
                        2,
                    )
                    cv2.putText(
                        image,
                        f"Fire {confi:.2f}",
                        (coords[0], coords[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 255),
                        2,
                    )
                    final_status = "UnSafe"
                    reason.add("fire")

                elif clas == 1:
                    cv2.rectangle(
                        image,
                        (coords[0], coords[1]),
                        (coords[2], coords[3]),
                        (0, 128, 255),
                        2,
                    )
                    cv2.putText(
                        image,
                        f"Smoke {confi:.2f}",
                        (coords[0], coords[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 128, 255),
                        2,
                    )
                    final_status = "UnSafe"
                    reason.add("smoke")

    color_status = (0, 0, 255) if final_status == "UnSafe" else (0, 255, 0)
    cv2.putText(
        image,
        final_status,
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        color_status,
        3,
    )
    if len(reason) != 0:
        i = 0
        for x in reason:
            cv2.putText(
                image,
                x,
                (40, 75 + i),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255) if x == "Fire Detected" else (0, 128, 255),
                3,
            )
            i = i + 25
    return final_status, list(reason), None
