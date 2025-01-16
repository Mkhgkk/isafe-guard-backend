import cv2
import numpy as np
from typing import List, Optional, Tuple
from ultralytics.engine.results import Results


def detect_mobile_scaffolding(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], Optional[List[Tuple[int, int, int, int]]]]:

    worker_with_helmet = []
    worker_without_helmet = []
    mobile_scaffold_outrigger = []
    final_status = "Safe"
    final_message = []

    for result in results:
        for x0, y0, x1, y1, confi, clas in result.boxes.data:  # type: ignore
            if confi > 0.6:
                box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                box2 = [int(x0), int(y0), int(x1), int(y1)]
                if int(clas) == 0:
                    cv2.rectangle(image, box, (0, 0, 255), 2)
                    cv2.putText(
                        image,
                        "Missing Guardrail {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2,
                    )
                    final_status = "UnSafe"
                    final_message.append("missing_guardrail")
                elif int(clas) == 1:
                    cv2.rectangle(image, box, (0, 0, 255), 2)
                    cv2.putText(
                        image,
                        "mobile_scaffold_no_outtrigger {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2,
                    )
                    final_status = "UnSafe"
                    final_message.append("mobile_scaffold_no_outtrigger")
                    mobile_scaffold_outrigger.append(box2)
                elif int(clas) == 2:
                    cv2.rectangle(image, box, (0, 255, 0), 2)
                    cv2.putText(
                        image,
                        "mobile_scaffold_outtrigger {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 128, 0),
                        2,
                    )
                    mobile_scaffold_outrigger.append(box2)
                elif int(clas) == 3:
                    cv2.rectangle(image, box, (0, 128, 0), 2)
                    cv2.putText(
                        image,
                        "worker_with_helmet {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 128, 0),
                        2,
                    )
                    worker_with_helmet.append(box2)
                elif int(clas) == 4:
                    cv2.rectangle(image, box, (0, 0, 255), 2)
                    cv2.putText(
                        image,
                        "worker_without_helmet {:.2f}".format(confi),
                        (box[0], box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 255),
                        2,
                    )
                    final_status = "UnSafe"
                    final_message.append("missing_helment")

    total_no_person_on_scaffolding = 0
    for scaff_box in mobile_scaffold_outrigger:
        for per_box in worker_with_helmet:
            if int(scaff_box[0]) < int(per_box[0]) < int(scaff_box[2]):
                center_y_scaffolding = int((scaff_box[1] + scaff_box[3]) / 2)
                if center_y_scaffolding >= per_box[3] - 20:
                    total_no_person_on_scaffolding += 1

    if total_no_person_on_scaffolding > 2:
        final_status = "UnSafe"
        final_message.append(f"{total_no_person_on_scaffolding} Worker")

    color_status = (0, 0, 255) if final_status == "UnSafe" else (0, 255, 0)
    cv2.putText(
        image,
        f"{final_status} : {' '.join(final_message)}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        color_status,
        2,
    )
    return final_status, final_message, None
