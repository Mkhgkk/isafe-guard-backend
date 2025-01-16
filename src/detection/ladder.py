import cv2
import numpy as np
from typing import List, Optional, Tuple
from ultralytics.engine.results import Results


def detect_ladder(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:

    global_behaviour = "Safe"
    worker = []
    ladder = []
    reason = []

    finalStatus = ""

    for result in results:
        for x0, y0, x1, y1, confi, clas in result.boxes.data:  # type: ignore
            if confi > 0.35:
                box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                box2 = [int(x0), int(y0), int(x1), int(y1)]
                if int(clas) == 0:
                    cv2.rectangle(image, box, (0, 128, 0), 2)
                    cv2.putText(
                        image,
                        "ladder_with_outriggers {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        (0, 128, 0),
                        2,
                    )
                    ladder.append(box2)
                elif int(clas) == 1:
                    global_behaviour = "UnSafe"
                    if "Ladder without Outtrigger" not in reason:
                        reason.append("ladder_without_outtrigger")
                        ladder.append(box2)
                    cv2.rectangle(image, box, (0, 0, 255), 2)
                    cv2.putText(
                        image,
                        "ladder_without_outriggers {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.2,
                        (0, 0, 255),
                        2,
                    )
                elif int(clas) == 2 or int(clas) == 3:
                    worker.append((box2, box, int(clas)))
                    if int(clas) == 3:
                        global_behaviour = "UnSafe"
                        if "Worker Without Helmet" not in reason:
                            reason.append("missing_helment")

    worker_height = 0
    co_worker = 0
    worker_with_height = []
    worker_without_height = []
    highest_height = -1

    for worker_box, worker_box_bounding, worker_class in worker:
        if len(ladder) == 0:
            color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
            label = (
                "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
            )
            cv2.rectangle(image, worker_box_bounding, color, 2)
            cv2.putText(
                image,
                "{} {:.2f}".format(label, confi),
                (worker_box_bounding[0], worker_box_bounding[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.25,
                color,
                2,
            )

    for ladder_box in ladder:
        for worker_box, worker_box_bounding, worker_class in worker:
            if (ladder_box[0] <= worker_box[0] <= ladder_box[2]) or (
                ladder_box[0] <= worker_box[2] <= ladder_box[2]
            ):
                ladder_height_in_px = ladder_box[3] - ladder_box[1]
                worker_height_in_px = ladder_box[3] - worker_box[3]
                worker_height_in_percentage = (
                    worker_height_in_px / ladder_height_in_px
                ) * 100.0
                worker_height = round((worker_height_in_percentage / 100.0) * 2.0, 2)
                if highest_height < worker_height:
                    highest_height = worker_height
                    worker_with_height.insert(
                        0,
                        (
                            worker_box,
                            worker_box_bounding,
                            worker_class,
                            worker_height,
                        ),
                    )
                else:
                    worker_with_height.append(
                        (
                            worker_box,
                            worker_box_bounding,
                            worker_class,
                            worker_height,
                        )
                    )
            else:
                worker_without_height.append(
                    (worker_box, worker_box_bounding, worker_class)
                )

    for worker_box, worker_box_bounding, worker_class in worker_without_height:
        color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
        label = "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
        cv2.rectangle(image, worker_box_bounding, color, 2)
        cv2.putText(
            image,
            "{} {:.2f}".format(label, confi),
            (worker_box_bounding[0], worker_box_bounding[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            color,
            2,
        )

    for x, (
        worker_box,
        worker_box_bounding,
        worker_class,
        height_ladder_worker,
    ) in enumerate(worker_with_height):
        if x == 0:
            color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
            label = (
                "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
            )
            cv2.rectangle(image, worker_box_bounding, color, 2)
            cv2.putText(
                image,
                "{} {:.2f}".format(label, confi),
                (worker_box_bounding[0], worker_box_bounding[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                color,
                2,
            )
        else:
            co_worker += 1
            color = (219, 252, 3) if worker_class == 2 else (252, 3, 219)
            label = (
                "CO-worker_with_helmet"
                if worker_class == 2
                else "CO-worker_without_helmet"
            )
            cv2.rectangle(image, worker_box_bounding, color, 2)
            cv2.putText(
                image,
                "{} {:.2f}".format(label, confi),
                (worker_box_bounding[0], worker_box_bounding[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.25,
                color,
                2,
            )

    worker_height = highest_height
    if highest_height >= 1.2:
        reason.append(f"Unsafe height : {worker_height} m")

    if highest_height >= 1.2 and co_worker == 0:
        global_behaviour = "UnSafe"
    else:
        worker_height = max(worker_height, 0)

    finalStatus = global_behaviour
    if finalStatus != "Safe":
        cv2.putText(
            image,
            (
                f"{finalStatus} : Height : {worker_height} m"
                if worker_height and worker_height < 1.2
                else f"{finalStatus}"
            ),
            (50, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (0, 0, 255),
            2,
        )
        for increment, rea in enumerate(reason, start=90):
            cv2.putText(
                image,
                f"{rea}",
                (50, increment),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.25,
                (0, 0, 255),
                2,
            )
    else:
        cv2.putText(
            image,
            f"{finalStatus}  Height : {worker_height} ",
            (50, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.25,
            (0, 255, 0),
            2,
        )

    return finalStatus, reason, None
