import os
import cv2
import time
import logging
import datetime
import numpy as np
from typing import List, Optional, Tuple
from ultralytics import YOLO
from detection.ppe import detect_ppe
from detection.scaffolding import detect_scaffolding
from detection.mobile_scaffolding import detect_mobile_scaffolding
from detection.ladder import detect_ladder
from detection.cutting_welding import detect_cutting_welding
from detection.fire_smoke import detect_fire_smoke
from ultralytics.engine.results import Results

MODELS_PATH = video_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../models")
)
PRECISION = "fp16"


class Detector:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model = self._load_model()

    def _load_model(self) -> YOLO:
        """
        :raises ValueError: If the model name is not recognized.
        """
        model_paths = {
            "PPE": os.path.join(MODELS_PATH, f"ppe/{PRECISION}/model.engine"),
            "PPEAerial": os.path.join(
                MODELS_PATH, f"ppe_aerial/{PRECISION}/model.engine"
            ),
            "Ladder": os.path.join(MODELS_PATH, f"ladder/{PRECISION}/model.engine"),
            "MobileScaffolding": os.path.join(
                MODELS_PATH, f"mobile_scaffolding/{PRECISION}/model.engine"
            ),
            "Scaffolding": os.path.join(
                MODELS_PATH, f"scaffolding/{PRECISION}/model.engine"
            ),
            "CuttingWelding": os.path.join(
                MODELS_PATH, f"cutting_welding/{PRECISION}/model.engine"
            ),
            "Fire": os.path.join(MODELS_PATH, f"fire_smoke/{PRECISION}/model.engine"),
        }

        model_path = model_paths.get(self.model_name)
        if not model_path:
            logging.error(f"Model name '{self.model_name}' is not recognized.")
            raise ValueError(f"Unknown model name: {self.model_name}")

        logging.info(f"Loading model: {self.model_name}")
        return YOLO(model_path)

    def detect(
        self, frame: np.ndarray
    ) -> Tuple["np.ndarray", str, List[str], Optional[List[Tuple[int, int, int, int]]]]:
        results: List[Results] = self.model(frame)
        final_status: str = "Safe"
        reasons: List[str] = []
        bboxes: Optional[List[Tuple[int, int, int, int]]] = None

        if self.model_name in ["PPE", "PPEAerial"]:
            result = detect_ppe(frame, results)
        elif self.model_name == "Ladder":
            result = detect_ladder(frame, results)
        elif self.model_name == "MobileScaffolding":
            result = detect_mobile_scaffolding(frame, results)
        elif self.model_name == "Scaffolding":
            result = detect_scaffolding(frame, results)
        elif self.model_name == "Fire":
            result = detect_fire_smoke(frame, results)
        elif self.model_name == "CuttingWelding":
            result = detect_cutting_welding(frame, results)
        else:
            logging.error(f"Model name '{self.model_name}' is not recognized.")
            raise ValueError(f"Unknown model name: {self.model_name}")

        final_status = result[0]
        reasons = result[1] if len(result) > 1 else []
        bboxes = result[2] if len(result) > 2 else None

        # return frame, final_status, [reasons], bboxes
        return frame, final_status, reasons, bboxes
