import os
import datetime
import cv2
from ultralytics import YOLO
from autotrack import PTZAutoTracker

tracker = PTZAutoTracker()

class ObjectDetection:
    def __init__(self):
        # Define paths for model storage
        PROJECT_PATH = os.path.abspath(os.getcwd())
        MODELS_PATH = os.path.join(PROJECT_PATH, "models")

        # Load YOLO models
        self.models = {
            "PPE": YOLO(os.path.join(MODELS_PATH, "PPEbest.pt")),
            "Ladder": YOLO(os.path.join(MODELS_PATH, "Ladder_yolov8.pt")),
            "MobileScaffolding": YOLO(os.path.join(MODELS_PATH, "MobileScaffoldingbest.pt")),
            "Scaffolding": YOLO(os.path.join(MODELS_PATH, "best_2024_scafolding.pt")),
            "CuttingWelding": YOLO(os.path.join(MODELS_PATH, "cutting_welding_yolov8.pt")),
        }

    def detect_ppe(self, image, results):
        person_boxes = []
        hat_boxes = []
        final_status = "Safe"

        for result in results:
            for box in result.boxes.data:
                coords = list(map(int, box[:4]))
                confi = float(box[4])
                clas = int(box[5])
                if confi > 0.6:
                    if clas == 1:
                        cv2.rectangle(image, (coords[0], coords[1]), (coords[2], coords[3]), (0, 255, 0), 2)
                        cv2.putText(image, f"Hard Hat {confi:.2f}", (coords[0], coords[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        hat_boxes.append(coords)
                    elif clas == 2:
                        person_boxes.append(coords)

        for perBox in person_boxes:
            hatDetected = any(perBox[0] <= (hatBox[0] + hatBox[2]) / 2 < perBox[2] and hatBox[1] >= perBox[1] - 20 for hatBox in hat_boxes)
            if hatDetected:
                cv2.rectangle(image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), (0, 180, 0), 2)
                cv2.putText(image, "Worker with helmet", (perBox[0], perBox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 180, 0), 2)
            else:
                final_status = "UnSafe"
                # autotrack from here
                # desired_width, desired_height = 1280, 720 
                tracker.track(1280, 720, perBox)
                cv2.rectangle(image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), (0, 0, 255), 2)
                cv2.putText(image, "Worker without helmet", (perBox[0], perBox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        color_status = (0, 0, 255) if final_status == "UnSafe" else (0, 255, 0)
        cv2.putText(image, final_status, (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, color_status, 3)
        return final_status

    def detect_ladder(self, image, results):
        global_behaviour = "Safe"
        worker = []
        ladder = []
        reason = []

        finalStatus = ""

        for result in results:
            for (x0, y0, x1, y1, confi, clas) in result.boxes.data:
                if confi > 0.35:
                    box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                    box2 = [int(x0), int(y0), int(x1), int(y1)]
                    if int(clas) == 0:
                        cv2.rectangle(image, box, (0, 128, 0), 2)
                        cv2.putText(image, "ladder_with_outriggers {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 128, 0), 2)
                        ladder.append(box2)
                    elif int(clas) == 1:
                        global_behaviour = "UnSafe"
                        if "Ladder without Outtrigger" not in reason:
                            reason.append("Ladder without Outtrigger")
                            ladder.append(box2)
                        cv2.rectangle(image, box, (0, 0, 255), 2)
                        cv2.putText(image, "ladder_without_outriggers {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 2)
                    elif int(clas) == 2 or int(clas) == 3:
                        worker.append((box2, box, int(clas)))
                        if int(clas) == 3:
                            global_behaviour = "UnSafe"
                            if 'Worker Without Helmet' not in reason:
                                reason.append("Worker Without Helmet")

        worker_height = 0
        co_worker = 0
        worker_with_height = []
        worker_without_height = []
        highest_height = -1

        for worker_box, worker_box_bounding, worker_class in worker:
            if len(ladder) == 0:
                color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
                label = "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
                cv2.rectangle(image, worker_box_bounding, color, 2)
                cv2.putText(image, "{} {:.2f}".format(label, confi),
                            (worker_box_bounding[0], worker_box_bounding[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.25,
                            color, 2)

        for ladder_box in ladder:
            for worker_box, worker_box_bounding, worker_class in worker:
                if ((ladder_box[0] <= worker_box[0] <= ladder_box[2]) or (
                        ladder_box[0] <= worker_box[2] <= ladder_box[2])):
                    ladder_height_in_px = ladder_box[3] - ladder_box[1]
                    worker_height_in_px = ladder_box[3] - worker_box[3]
                    worker_height_in_percentage = (worker_height_in_px / ladder_height_in_px) * 100.0
                    worker_height = round((worker_height_in_percentage / 100.0) * 2.0, 2)
                    if highest_height < worker_height:
                        highest_height = worker_height
                        worker_with_height.insert(0, (worker_box, worker_box_bounding, worker_class, worker_height))
                    else:
                        worker_with_height.append((worker_box, worker_box_bounding, worker_class, worker_height))
                else:
                    worker_without_height.append((worker_box, worker_box_bounding, worker_class))

        for worker_box, worker_box_bounding, worker_class in worker_without_height:
            color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
            label = "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
            cv2.rectangle(image, worker_box_bounding, color, 2)
            cv2.putText(image, "{} {:.2f}".format(label, confi),
                        (worker_box_bounding[0], worker_box_bounding[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.25,
                        color, 2)

        for x, (worker_box, worker_box_bounding, worker_class, height_ladder_worker) in enumerate(
                worker_with_height):
            if x == 0:
                color = (0, 255, 0) if worker_class == 2 else (0, 0, 255)
                label = "worker_with_helmet" if worker_class == 2 else "worker_without_helmet"
                cv2.rectangle(image, worker_box_bounding, color, 2)
                cv2.putText(image, "{} {:.2f}".format(label, confi),
                            (worker_box_bounding[0], worker_box_bounding[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                            color, 2)
            else:
                co_worker += 1
                color = (219, 252, 3) if worker_class == 2 else (252, 3, 219)
                label = "CO-worker_with_helmet" if worker_class == 2 else "CO-worker_without_helmet"
                cv2.rectangle(image, worker_box_bounding, color, 2)
                cv2.putText(image, "{} {:.2f}".format(label, confi),
                            (worker_box_bounding[0], worker_box_bounding[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.25,
                            color, 2)

        worker_height = highest_height
        if highest_height >= 1.2:
            reason.append(f"Unsafe height : {worker_height} m")

        if highest_height >= 1.2 and co_worker == 0:
            global_behaviour = "UnSafe"
        else:
            worker_height = max(worker_height, 0)

        finalStatus = global_behaviour
        if finalStatus != "Safe":
            cv2.putText(image,
                        f"{finalStatus} : Height : {worker_height} m" if worker_height and worker_height < 1.2 else f"{finalStatus}",
                        (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (0, 0, 255), 2)
            for increment, rea in enumerate(reason, start=90):
                cv2.putText(image, f"{rea}", (50, increment), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (0, 0, 255), 2)
        else:
            cv2.putText(image, f"{finalStatus}  Height : {worker_height} ", (50, 50), cv2.FONT_HERSHEY_SIMPLEX,
                        1.25, (0, 255, 0), 2)

        return finalStatus

    def detect_mobile_scaffolding(self, image, results):
        worker_with_helmet = []
        worker_without_helmet = []
        mobile_scaffold_outrigger = []
        final_status = "Safe"
        final_message = []

        for result in results:
            for (x0, y0, x1, y1, confi, clas) in result.boxes.data:
                if confi > 0.6:
                    box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                    box2 = [int(x0), int(y0), int(x1), int(y1)]
                    if int(clas) == 0:
                        cv2.rectangle(image, box, (0, 0, 255), 2)
                        cv2.putText(image, "Missing Guardrail {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        final_status = "UnSafe"
                        final_message.append("Missing Guardrail")
                    elif int(clas) == 1:
                        cv2.rectangle(image, box, (0, 0, 255), 2)
                        cv2.putText(image, "mobile_scaffold_no_outtrigger {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        final_status = "UnSafe"
                        final_message.append("No outrigger")
                        mobile_scaffold_outrigger.append(box2)
                    elif int(clas) == 2:
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "mobile_scaffold_outtrigger {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 128, 0), 2)
                        mobile_scaffold_outrigger.append(box2)
                    elif int(clas) == 3:
                        cv2.rectangle(image, box, (0, 128, 0), 2)
                        cv2.putText(image, "worker_with_helmet {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 128, 0), 2)
                        worker_with_helmet.append(box2)
                    elif int(clas) == 4:
                        cv2.rectangle(image, box, (0, 0, 255), 2)
                        cv2.putText(image, "worker_without_helmet {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        final_status = "UnSafe"
                        final_message.append("Missing Helmet")

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
        cv2.putText(image, f"{final_status} : {' '.join(final_message)}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color_status, 2)
        return final_status

    def detect_scaffolding(self, image, results):
        person = []
        hat = []
        hook = []
        o_hatch = 0
        c_hatch = 0
        final_status = ""

        for result in results:
            for (x0, y0, x1, y1, confi, clas) in result.boxes.data:
                if confi > 0.6:
                    box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                    box2 = [int(x0), int(y0), int(x1), int(y1)]
                    box3 = [int(x0), int(y0), int(x1), int(y1)]
                    if int(clas) == 3:
                        cv2.rectangle(image, box, (0, 130, 0), 2)
                        cv2.putText(image, "hook {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2)
                        hook.append(box3)
                    elif int(clas) == 2:
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "Hard Hat {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        hat.append(box2)
                    elif int(clas) == 4:
                        o_hatch += 1
                        cv2.rectangle(image, box, (0, 0, 255), 2)
                        cv2.putText(image, "opened_hatch {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    elif int(clas) == 5:
                        c_hatch += 1
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "closed_hatch {:.2f}".format(confi), (box[0], box[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    elif int(clas) == 1:
                        person.append(box2)

        class_worker_count = len(person)
        class_helmet_count = len(hat)
        class_hook_count = len(hook)

        missing_hooks = max(0, class_worker_count - class_hook_count)
        missing_helmet = max(0, class_worker_count - class_helmet_count)

        #final_status = "Safe" if missing_helmet == 0 and missing_hooks == 0 and c_hatch >= 0 else "UnSafe"
        final_status = "Safe" if missing_helmet == 0 and missing_hooks == 0 else "UnSafe"

        for perBox in person:
            hatDetected = any(int(hatBox[0]) > int(perBox[0]) and int(hatBox[2]) < int(perBox[2]) and hatBox[1] >= perBox[1] - 20 for hatBox in hat)
            color = (0, 180, 0) if hatDetected else (0, 0, 255)
            cv2.rectangle(image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), color, 2)
            status_text = "Person with helmet" if hatDetected else "Person without helmet"
            cv2.putText(image, status_text, (perBox[0], perBox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 2)
            if not hatDetected:
                final_status = "UnSafe"

        color_status = (0, 0, 255) if final_status != "Safe" else (0, 255, 0)
        color_hooks = (0, 255, 0) if missing_hooks == 0 else (0, 0, 255)
        color_helmet = (0, 255, 0) if missing_helmet == 0 else (0, 0, 255)

        cv2.putText(image, f"{final_status}", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color_status, 3)
        cv2.putText(image, f"[Missing {missing_hooks} hooks]", (135, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color_hooks, 2)
        cv2.putText(image, f"[Missing {missing_helmet} helmet]", (135, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color_helmet, 2)
        return final_status

    def detect_cutting_welding(self, image, results):
        person = []
        hat = []
        final_status = "Safe"
        saw = fire_extinguisher = fire_prevention_net = False

        for result in results:
            for (x0, y0, x1, y1, confi, clas) in result.boxes.data:
                if confi > 0.6:
                    box = [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]
                    box2 = [int(x0), int(y0), int(x1), int(y1)]
                    if int(clas) == 0:
                        cv2.rectangle(image, box, (0, 130, 0), 2)
                        cv2.putText(image, "Saw {:.2f}".format(confi), (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 2)
                        saw = True
                    elif int(clas) == 1:
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "Fire Extinguisher {:.2f}".format(confi), (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        fire_extinguisher = True
                    elif int(clas) == 2:
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "Fire Prevention Net {:.2f}".format(confi), (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        fire_prevention_net = True
                    elif int(clas) == 3:
                        cv2.rectangle(image, box, (0, 255, 0), 2)
                        cv2.putText(image, "Hard Hat {:.2f}".format(confi), (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                        hat.append(box2)
                    elif int(clas) == 5:
                        person.append(box2)

        for perBox in person:
            hatDetected = any(int((hatBox[0] + hatBox[2]) / 2) > int(perBox[0]) and int((hatBox[0] + hatBox[2]) / 2) < int(perBox[2]) and hatBox[1] >= perBox[1] - 20 for hatBox in hat)
            color = (0, 180, 0) if hatDetected else (0, 0, 255)
            cv2.rectangle(image, (perBox[0], perBox[1]), (perBox[2], perBox[3]), color, 2)
            status_text = "Worker with Hardhat" if hatDetected else "Worker without HardHat"
            cv2.putText(image, status_text, (perBox[0], perBox[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if not hatDetected:
                final_status = "UnSafe"

        if fire_extinguisher:
            cv2.putText(image, "Fire Extinguisher: Detected", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
        else:
            final_status = "UnSafe"
            cv2.putText(image, "Fire Extinguisher: Missing", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

        if saw:
            if fire_prevention_net:
                cv2.putText(image, "Cutting: Fire Prevention Net detected", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
            else:
                final_status = "UnSafe"
                cv2.putText(image, "Cutting: Fire Prevention Net Missing", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

        color_status = (0, 0, 255) if final_status != "Safe" else (0, 255, 0)
        cv2.putText(image, f"{final_status} ", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, color_status, 3)
        return final_status

    def detectObj(self, image, timestamp, model_name):
        print(f"Processing frame with model: {model_name}")
        start_time = datetime.datetime.now()
        model = self.models.get(model_name)

        if not model:
            raise ValueError(f"Model '{model_name}' not found!")

        results = model(image)
        print("Detection results:", results)

        detection_handlers = {
            "PPE": self.detect_ppe,
            "Ladder": self.detect_ladder,
            "MobileScaffolding": self.detect_mobile_scaffolding,
            "Scaffolding": self.detect_scaffolding,
            "CuttingWelding": self.detect_cutting_welding,
        }

        final_status = detection_handlers[model_name](image, results)

        inference_time = (datetime.datetime.now() - start_time).total_seconds()
        return image, timestamp, final_status, inference_time