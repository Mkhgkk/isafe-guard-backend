import cv2
import numpy as np
from typing import List, Optional, Tuple
from ultralytics.engine.results import Results


def detect_cutting_welding(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:

    person = []
    hat = []
    final_status = "Safe"
    saw = fire_extinguisher = fire_prevention_net = False
    reasons = []

    for result in results:
        for x0, y0, x1, y1, confi, clas in result.boxes.data:  # type: ignore
            if confi > 0.6:
                box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                box2 = [int(x0), int(y0), int(x1), int(y1)]
                if int(clas) == 0:
                    cv2.rectangle(image, box, (0, 130, 0), 2)
                    cv2.putText(
                        image,
                        "Saw {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 200, 0),
                        2,
                    )
                    saw = True
                elif int(clas) == 1:
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    cv2.putText(
                        image,
                        "Fire Extinguisher {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )
                    fire_extinguisher = True
                elif int(clas) == 2:
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    cv2.putText(
                        image,
                        "Fire Prevention Net {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )
                    fire_prevention_net = True
                elif int(clas) == 3:
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    cv2.putText(
                        image,
                        "Hard Hat {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2,
                    )
                    hat.append(box2)
                elif int(clas) == 5:
                    person.append(box2)

    for perBox in person:
        hatDetected = any(
            int((hatBox[0] + hatBox[2]) / 2) > int(perBox[0])
            and int((hatBox[0] + hatBox[2]) / 2) < int(perBox[2])
            and hatBox[1] >= perBox[1] - 20
            for hatBox in hat
        )
        color = (0, 180, 0) if hatDetected else (0, 0, 255)
        cv2.rectangle(image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), color, 2)
        status_text = "Worker with Hardhat" if hatDetected else "Worker without HardHat"
        cv2.putText(
            image,
            status_text,
            (perBox[0], perBox[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )
        if not hatDetected:
            final_status = "UnSafe"
            reasons.append("missing_helmet")

    if fire_extinguisher:
        cv2.putText(
            image,
            "Fire Extinguisher: Detected",
            (50, 100),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            3,
        )
    else:
        final_status = "UnSafe"
        cv2.putText(
            image,
            "Fire Extinguisher: Missing",
            (50, 100),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            3,
        )
        reasons.append("missing_fire_extinguisher")

    if saw:
        if fire_prevention_net:
            cv2.putText(
                image,
                "Cutting: Fire Prevention Net detected",
                (50, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                3,
            )
        else:
            final_status = "UnSafe"
            cv2.putText(
                image,
                "Cutting: Fire Prevention Net Missing",
                (50, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                3,
            )
            reasons.append("missing_fire_net")

    color_status = (0, 0, 255) if final_status != "Safe" else (0, 255, 0)
    cv2.putText(
        image,
        f"{final_status} ",
        (50, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        color_status,
        3,
    )
    return final_status, reasons, None
