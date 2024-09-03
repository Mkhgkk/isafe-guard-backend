import os
import time
import subprocess
import datetime
import cv2
import numpy as np
from ultralytics import YOLO
from collections import deque
from threading import Thread
from queue import Queue
from flask import Flask, Response, render_template, request, jsonify
import threading
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room, send
import asyncio
from camera_controller import CameraController

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


class VideoStreaming:
    def __init__(self, rtsp_link, model_name, stream_id):
        # self.app = app
        self.VIDEO = None  # Initialize without opening a stream
        self.MODEL = ObjectDetection()
        # self.db = db
        # self.EventVideo = EventVideo
        self.fps_queue = deque(maxlen=30)
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        self.frames_written = 0
        self.video_name = None

        self.frame_buffer = deque(maxlen=10)
        self.running = False

        self.lock = threading.Lock()

        self.streams_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name

    @property
    def preview(self):
        return self._preview

    @preview.setter
    def preview(self, value):
        self._preview = bool(value)

    @property
    def flipH(self):
        return self._flipH

    @flipH.setter
    def flipH(self, value):
        self._flipH = bool(value)

    @property
    def detect(self):
        return self._detect

    @detect.setter
    def detect(self, value):
        self._detect = bool(value)

    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, value):
        self._exposure = value
        self.VIDEO.set(cv2.CAP_PROP_EXPOSURE, self._exposure)

    @property
    def contrast(self):
        return self._contrast

    @contrast.setter
    def contrast(self, value):
        self._contrast = value
        self.VIDEO.set(cv2.CAP_PROP_CONTRAST, self._contrast)

    def process_video(self, snap, model_name, out, video_count, result_queue):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if self._detect:
            if out is None:
                # Use default FPS of 20 if CAP_PROP_FPS returns 0 or invalid
                fps = self.VIDEO.get(cv2.CAP_PROP_FPS) or 20
                out, self.video_name = self.create_video_writer(snap, timestamp, model_name, fps)
            print("After: ", self.video_name)
            snap, timestamp, finalStatus, inference_time = self.MODEL.detectObj(snap, timestamp, model_name)
            self.total_frame_count += 1
            if finalStatus == "UnSafe" and out is not None:
                out.write(snap)
                self.unsafe_frame_count += 1
                self.frames_written += 1

        result_queue.put((snap, out, self.total_frame_count, timestamp, self.video_name))



    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)  # Open the stream with the given RTSP link
    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20  # Use a default FPS if not available
    #     out = None
    #     frame_interval = int(3 * fps)  # Check status every 3 seconds
    #     record_duration = int(5 * fps)  # Record 5 seconds video
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # # Check if we should save the video
    #         # total_frame_count += 1
    #         # if total_frame_count % frame_interval == 0:
    #         #     unsafe_ratio = unsafe_frame_count / frame_interval if frame_interval else 0
    #         #     if unsafe_ratio >= 0.7:
    #         #         if total_frame_count % record_duration == 0:
    #         #             self.save_event_video(video_name, timestamp, camera_id=None)  # Pass camera_id if needed
    #         #             if out is not None:
    #         #                 out.release()
    #         #                 out = None
    #         #             unsafe_frame_count = 0

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Encode frame for streaming
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #                b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         time.sleep(0.01)

    #     video_capture.release()

    # =========================================
    # =========================================
    # =========================================
    

    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)  # Open the stream with the given RTSP link
    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20  # Use a default FPS if not available
    #     out = None
    #     frame_interval = int(3 * fps)  # Check status every 3 seconds
    #     record_duration = int(5 * fps)  # Record 5 seconds video
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     # Open a new window to display the stream
    #     cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Display the frame in the window
    #         cv2.imshow("Stream", processed_frame)

    #         # Stream over HTTP (if needed)
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #             b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         # Exit condition for the OpenCV window
    #         if cv2.waitKey(1) & 0xFF == ord('q'):
    #             break

    #         time.sleep(0.01)

    #     # Clean up and close the window
    #     video_capture.release()
    #     cv2.destroyAllWindows()
    #     if out is not None:
    #         out.release()

    # =========================================
    # =========================================
    # =========================================


    def show(self, model_name, rtsp_link):
        video_capture = cv2.VideoCapture(rtsp_link)
        if not video_capture.isOpened():
            print(f"Error: Unable to open video stream from {rtsp_link}")
            return

        fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
        out = None
        frame_interval = int(3 * fps)
        record_duration = int(5 * fps)
        total_frame_count = 0
        unsafe_frame_count = 0
        frames_written = 0
        video_name = None
        fps_queue = deque(maxlen=30)

        # Optimize by reducing frame size
        # desired_width = 640
        # desired_height = 480
        # desired_width = 800
        # desired_height = 600
        desired_width = 1280
        desired_height = 720


        cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

        while video_capture.isOpened():
            ret, frame = video_capture.read()
            if not ret:
                print(f"Failed to read from {rtsp_link}")
                break

            # Resize frame to desired dimensions
            frame = cv2.resize(frame, (desired_width, desired_height))

            processed_frame, final_status = self.apply_model(frame, model_name)

            if final_status == "UnSafe":
                if out is None:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
                out.write(processed_frame)
                unsafe_frame_count += 1
                frames_written += 1

            fps_queue.append(time.time())
            fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
            cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            cv2.imshow("Stream", processed_frame)

            # Exit condition for the OpenCV window
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            time.sleep(0.01)

        video_capture.release()
        cv2.destroyAllWindows()
        if out is not None:
            out.release()


    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)
    #     if not video_capture.isOpened():
    #         print(f"Error: Unable to open video stream from {rtsp_link}")
    #         return

    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
    #     out = None
    #     frame_interval = int(3 * fps)
    #     record_duration = int(5 * fps)
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     # Desired width and height
    #     # desired_width = 640
    #     # desired_height = 480
    #     desired_width = 800
    #     desired_height = 600

    #     cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Get original frame dimensions
    #         original_height, original_width = frame.shape[:2]

    #         # Calculate aspect ratio of the original frame
    #         aspect_ratio = original_width / original_height

    #         # Calculate the new dimensions while maintaining aspect ratio
    #         if aspect_ratio > 1:  # Wider than tall
    #             new_width = desired_width
    #             new_height = int(desired_width / aspect_ratio)
    #         else:  # Taller than wide or square
    #             new_height = desired_height
    #             new_width = int(desired_height * aspect_ratio)

    #         # Resize the frame to the new dimensions
    #         frame_resized = cv2.resize(frame, (new_width, new_height))

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame_resized, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(processed_frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Display the frame in the window
    #         cv2.imshow("Stream", processed_frame)

    #         # Stream over HTTP (if needed)
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #             b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         # Exit condition for the OpenCV window
    #         if cv2.waitKey(1) & 0xFF == ord('q'):
    #             break

    #         time.sleep(0.01)

    #     # Clean up and close the window
    #     video_capture.release()
    #     cv2.destroyAllWindows()
    #     if out is not None:
    #         out.release()





    def apply_model(self, frame, model_name):
        # Detect objects using the specified model
        model = self.MODEL.models.get(model_name)
        if not model:
            raise ValueError(f"Model '{model_name}' not found!")

        results = model(frame)
        final_status = "Safe"

        if model_name == "PPE":
            final_status = self.MODEL.detect_ppe(frame, results)
        elif model_name == "Ladder":
            final_status = self.MODEL.detect_ladder(frame, results)
        elif model_name == "MobileScaffolding":
            final_status = self.MODEL.detect_mobile_scaffolding(frame, results)
        elif model_name == "Scaffolding":
            final_status = self.MODEL.detect_scaffolding(frame, results)
        elif model_name == "CuttingWelding":
            final_status = self.MODEL.detect_cutting_welding(frame, results)

        return frame, final_status

    def create_video_writer(self, frame, timestamp, model_name, output_fps):
        video_name1 = f"./static/unsafe/video_{model_name}_{timestamp}.mp4"  # Save videos as MP4 with timestamp
        video_name = f"/unsafe/video_{model_name}_{timestamp}.mp4"
        height, width, _ = frame.shape
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        return cv2.VideoWriter(video_name1, fourcc, output_fps, (width, height)), video_name

    # def save_event_video(self, video_path, timestamp, camera_id):
    #     with self.app.app_context():
    #         event_video = self.EventVideo(timestamp=timestamp, video_path=video_path, camera_id=camera_id)
    #         try:
    #             self.db.session.add(event_video)
    #             self.db.session.commit()
    #         except Exception as e:
    #             self.db.session.rollback()
    #             print(f"Error saving video event: {e}")
    def start_stream(self):
        self.running = True
        threading.Thread(target=self.generate_frames, args=("rtsp://admin:1q2w3e4r.@218.54.201.82:554/idis?trackid=2", "PPE"), daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, args=("PPE",), daemon=True).start()

    def stop_streaming(self): 
        self.running = False


    def generate_frames(self, rtsp_link, model_name):
        # Open the RTSP video stream
        video_capture = cv2.VideoCapture(self.rtsp_link)
        if not video_capture.isOpened():
            print(f"Error: Unable to open video stream from {self.rtsp_link}")
            return

        fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
        desired_width, desired_height = 1280, 720  # Set desired dimensions

        while self.running and video_capture.isOpened():
            ret, frame = video_capture.read()
            if not ret:
                print(f"Failed to read from {self.rtsp_link}")
                break

            # Resize frame to desired dimensions (perform this as early as possible)
            frame = cv2.resize(frame, (desired_width, desired_height))

            # Lock the buffer and add the frame to the buffer
            with self.lock:
                self.frame_buffer.append(frame)

        video_capture.release()

    def process_and_emit_frames(self, model_name):
        while self.running:
            with self.lock:
                if self.frame_buffer:
                    frame = self.frame_buffer.popleft()
                else:
                    frame = None

            if frame is not None:
                # Apply your detection model
                processed_frame, final_status = self.apply_model(frame, self.model_name)

                # Encode frame in JPEG format with lower quality for faster transmission
                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                frame_data = buffer.tobytes()

                # Emit frame to all connected clients
                # socketio.emit('frame', {'image': frame_data}, namespace='/video')
                socketio.emit(f'frame-{self.streams_id}', {'image': frame_data}, namespace='/video', room=self.streams_id)

            else:
                # If no frames are in the buffer, wait for a short time
                asyncio.sleep(0.001)

    # def apply_model(self, frame, model_name):
    #     # Simulate model processing (replace with actual model inference)
    #     processed_frame = frame  # No change for now
    #     final_status = "safe"  # Placeholder status
    #     return processed_frame, final_status

    # def stream_frames(self):
    #     while self.running:
    #         if self.frame_buffer:
    #             frame = self.frame_buffer.popleft()
    #             yield (b'--frame\r\n'
    #                    b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    #         else:
    #             time.sleep(0.001)  # Slight delay if buffer is empty

    def stop(self):
        self.running = False


app = Flask(__name__)
CORS(app)
# socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
cors = CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# video_streaming = VideoStreaming()
streams = {}
camera_controllers = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data', methods=['POST'])
def receive_data():
    # Check if the request contains JSON data
    if request.is_json:
        # Parse the JSON data from the request
        data = request.get_json()

        # Do something with the data (for example, print it or process it)
        print(f"Received data: {data}")

        # Create a response object
        response = {
            "status": "success",
            "message": "Data received successfully",
            "data": data
        }

        # Return a JSON response
        return jsonify(response), 200
    else:
        # Return an error response if the data is not in JSON format
        return jsonify({"status": "error", "message": "Request data must be JSON"}), 400


@app.route('/api/start_stream', methods=['POST'])
def start_stream():
    if request.is_json:
        data = request.get_json()

        rtsp_link = data["rtsp_link"]
        model_name = data["model_name"]
        stream_id = data["stream_id"]

        video_streaming = VideoStreaming(rtsp_link, model_name, stream_id)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # init ptz
        camera_controller = camera_controller = CameraController('192.168.0.133', 80, 'root', 'fsnetworks1!')
        camera_controllers[stream_id] = camera_controller

        response = {
            "status": "Success",
            "message": "Detector started successifully",
            "data": data
        }

        return jsonify(response), 200

    else:
        return jsonify({"status": "error", "message": "wrong data format!"}), 400

@app.route('/api/stop_stream', methods=['POST'])
def stop_stream():
    if request.is_json:
        data = request.get_json()

        stream_id = data["stream_id"]

        video_streaming = streams[stream_id]
        video_streaming.stop_streaming()

        del streams[stream_id]
        del camera_controllers[stream_id]

        response = {
            "status": "Success",
            "message": "Detector stopped successifully",
            "data": data
        }

        return jsonify(response), 200

    else:
        return jsonify({"status": "error", "message": "wrong data format!"}), 400



@socketio.on('connect', namespace='/video')
def video_connect():
    print('Client connected')
    # if not video_streaming.running:
    #     video_streaming.running = True
    #     threading.Thread(target=video_streaming.generate_frames, args=("rtsp://admin:1q2w3e4r.@218.54.201.82:554/idis?trackid=2", "PPE"), daemon=True).start()
    #     threading.Thread(target=video_streaming.process_and_emit_frames, args=("PPE",), daemon=True).start()

@socketio.on('disconnect', namespace='/video')
def video_disconnect():
    print('Client disconnected')
    # video_streaming.stop()

@socketio.on('join', namespace='/video')
def handle_join(data):
    room = data['room']  # Get room name from the received data
    join_room(room)
    send(f"{request.sid} has entered the room {room}.", room=room)

@socketio.on('leave', namespace='video')
def handle_leave(data):
    room = data['room']  # Get room name from the received data
    leave_room(room)
    send(f"{request.sid} has left the room {room}.", room=room)

@socketio.on('join_ptz', namespace='/video')
def join_ptz_room(data):
    stream_id = data["stream_id"]
    camera_controller = camera_controllers[stream_id]

    room = f"ptz-{stream_id}"
    join_room(room)

    zoom = camera_controller.get_zoom_level()
    socketio.emit(f'zoom-level', {'zoom': zoom}, namespace='/video', room=room)

@socketio.on('leave_ptz', namespace='/video')
def leave_ptz_room(data):
    stream_id = data["stream_id"]
    room = f"ptz-{stream_id}"

    leave_room(room)

@socketio.on('ptz_move', namespace='/video')
def ptz_change_zoom(data):
    stream_id = data["stream_id"]
    zoom_amount = data.get("zoom_amount", None)
    direction = data["direction"]
    stop = data.get("stop", False)
    camera_controller = camera_controllers[stream_id]
    room = f"ptz-{stream_id}"

    if direction == 'zoom_in':
        camera_controller.move_camera(direction, zoom_amount)
        socketio.emit(f'zoom-level', {'zoom': zoom_amount}, namespace='/video', room=room)
    elif stop is False:  
        camera_controller.move_camera(direction)
    elif stop is True: 
        camera_controller.stop_camera()


if __name__ == '__main__':
    # video_streaming.running = True
    # threading.Thread(target=video_streaming.generate_frames, args=("rtsp://admin:1q2w3e4r.@218.54.201.82:554/idis?trackid=2", "PPE"), daemon=True).start()
    # threading.Thread(target=video_streaming.process_and_emit_frames, args=("PPE",), daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

