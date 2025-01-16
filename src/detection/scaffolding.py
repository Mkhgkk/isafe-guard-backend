import cv2
import numpy as np
from typing import List, Optional, Tuple
from detection import draw_text_with_background
from ultralytics.engine.results import Results


def detect_scaffolding(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:

    person = []
    hat = []
    hook = []
    o_hatch = 0
    c_hatch = 0
    final_status = "Safe"
    reasons = []

    # Get image dimensions to scale the font and other elements accordingly
    img_height, img_width = image.shape[:2]
    font_scale = 0.8  # max(0.1, img_width / 1000)
    thickness = max(1, int(img_width / 500))

    for result in results:
        for x0, y0, x1, y1, confi, clas in result.boxes.data:  # type: ignore
            if confi > 0.3:
                box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                box2 = [int(x0), int(y0), int(x1), int(y1)]
                box3 = [int(x0), int(y0), int(x1), int(y1)]
                if int(clas) == 3:
                    cv2.rectangle(image, box, (0, 150, 0), 2)
                    draw_text_with_background(
                        image,
                        f"hook",
                        (box[0], box[1] - 10),
                        font_scale,
                        (0, 200, 0),
                        thickness,
                    )
                    hook.append(box3)
                elif int(clas) == 2:
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    draw_text_with_background(
                        image,
                        f"Hard Hat",
                        (box[0], box[1] - 10),
                        font_scale,
                        (0, 255, 0),
                        thickness,
                    )
                    hat.append(box2)
                elif int(clas) == 4:
                    o_hatch += 1
                    cv2.rectangle(image, box, (0, 0, 255), 2)
                    draw_text_with_background(
                        image,
                        f"opened_hatch",
                        (box[0], box[1] - 10),
                        font_scale,
                        (0, 0, 255),
                        thickness,
                    )
                elif int(clas) == 5:
                    c_hatch += 1
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    draw_text_with_background(
                        image,
                        f"closed_hatch",
                        (box[0], box[1] - 10),
                        font_scale,
                        (0, 255, 0),
                        thickness,
                    )
                elif int(clas) == 1:
                    person.append(box2)

    class_worker_count = len(person)
    # class_helmet_count = len(hat)
    class_hook_count = len(hook)
    class_helmet_count = 0
    missing_hooks = max(0, class_worker_count - class_hook_count)

    for perBox in person:
        hatDetected = False
        for hatBox in hat:
            if int(perBox[0]) <= (int(hatBox[0]) + int(hatBox[2])) / 2 < int(perBox[2]):
                if hatBox[1] >= perBox[1] - 20:
                    hatDetected = True

            color = (0, 120, 0) if hatDetected else (0, 0, 255)
            cv2.rectangle(
                image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), color, 2
            )
            # status_text = "작업자 안전모 착용" if hatDetected else "작업자 안전모 미착용"
            status_text = (
                "Worker with Helmet" if hatDetected else "Worker Without Helmet"
            )
            class_helmet_count += 1 if hatDetected else 0

            draw_text_with_background(
                image,
                status_text,
                (perBox[0], perBox[1] - 10),
                font_scale,
                color,
                thickness,
            )
            if not hatDetected:
                final_status = "UnSafe"
                # reasons.append("작업자 안전모 미착용")
                # reasons.append("missing_helment")

    missing_helmet = max(0, class_worker_count - class_helmet_count)
    vertical_person = False
    for i, perBox1 in enumerate(person):
        for j, perBox2 in enumerate(person):
            if i != j:
                if ((perBox1[1] + perBox1[3]) / 2) > perBox2[3] or (
                    (perBox2[1] + perBox2[3]) / 2
                ) > perBox1[3]:
                    # if perBox1[0] < perBox2[2] and perBox1[2] > perBox2[0]:
                    if (perBox1[0] - (perBox1[2] - perBox1[0]) / 2) < perBox2[2] and (
                        perBox1[2] + (perBox1[2] - perBox1[0]) / 2
                    ) > perBox2[0]:
                        vertical_person = True

    if vertical_person:
        # reasons.append("작업자 상하 동시 작업 진행 중")
        reasons.append("same_vertical_area")

    # color_status = (0, 0, 255) if final_status != "Safe" else (0, 128, 0)
    color_hooks = (0, 120, 0) if missing_hooks == 0 else (0, 0, 255)
    color_helmet = (0, 120, 0) if missing_helmet == 0 else (0, 0, 255)

    if missing_hooks > 0:
        final_status = "UnSafe"
        # reasons.append(f"안전고리 미체결")  # (f"Missing {missing_hooks} hooks")
        reasons.append(f"missing_hook")  # (f"Missing {missing_hooks} hooks")
        draw_text_with_background(
            image, f"Missing Hook", (50, 90), font_scale, color_hooks, thickness
        )
    if missing_helmet > 0:
        final_status = "UnSafe"
        # reasons.append(f"안전모 미착용")  # (f"Missing {missing_helmet} helmets")
        reasons.append(f"missing_helmet")  # (f"Missing {missing_helmet} helmets")
        draw_text_with_background(
            image, f"Missing Helmet", (50, 130), font_scale, color_helmet, thickness
        )

    if vertical_person:
        final_status = "UnSafe"
        draw_text_with_background(
            image,
            f"Working in same Vertical Area",
            (50, 170),
            font_scale,
            (0, 0, 255),
            thickness,
        )
    final_status = "Safe" if not reasons else "UnSafe"
    color_status = (0, 0, 255) if final_status != "Safe" else (0, 120, 0)

    # draw_text_with_background(image, "안전" if (final_status == "Safe") else "위험", (40, 50), font_scale, color_status, thickness)
    draw_text_with_background(
        image, final_status, (40, 50), 1.0, color_status, thickness
    )

    # return image, results, timestamp, final_status
    return final_status, reasons, None
