import os
import cv2
import time
from utils.logging_config import get_logger, log_event
import datetime
import numpy as np
from typing import List, Optional, Tuple
from ultralytics import YOLO

logger = get_logger(__name__)
from detection.ppe import detect_ppe
from detection.scaffolding import detect_scaffolding
from detection.mobile_scaffolding import detect_mobile_scaffolding
from detection.ladder import detect_ladder
from detection.cutting_welding import detect_cutting_welding
from detection.fire_smoke import detect_fire_smoke
from detection.heavy_equipment import detect_heavy_equipment
from detection.proximity import detect_proximity
from ultralytics.engine.results import Results

from config import DEFAULT_PRECISION
MODELS_PATH = video_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../models")
)


class Detector:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model = self._load_model()

    def _load_model(self) -> YOLO:
        """
        :raises ValueError: If the model name is not recognized.
        """
        model_paths = {
            "PPE": os.path.join(MODELS_PATH, f"ppe/{DEFAULT_PRECISION}/model.engine"),
            "PPEAerial": os.path.join(
                MODELS_PATH, f"ppe_aerial/{DEFAULT_PRECISION}/model.engine"
            ),
            "Ladder": os.path.join(MODELS_PATH, f"ladder/{DEFAULT_PRECISION}/model.engine"),
            "MobileScaffolding": os.path.join(
                MODELS_PATH, f"mobile_scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Scaffolding": os.path.join(
                MODELS_PATH, f"scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "CuttingWelding": os.path.join(
                MODELS_PATH, f"cutting_welding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Fire": os.path.join(MODELS_PATH, f"fire_smoke/{DEFAULT_PRECISION}/model.engine"),
            "HeavyEquipment": os.path.join(MODELS_PATH, f"heavy_equipment/{DEFAULT_PRECISION}/model.engine"),
            "Proximity": os.path.join(MODELS_PATH, f"proximity/{DEFAULT_PRECISION}/model.engine"),
        }

        model_path = model_paths.get(self.model_name)
        if not model_path:
            log_event(logger, "error", f"Model name '{self.model_name}' is not recognized.", event_type="error")
            raise ValueError(f"Unknown model name: {self.model_name}")

        log_event(logger, "info", f"Loading model: {self.model_name}", event_type="info")
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
        elif self.model_name == "HeavyEquipment":
            result = detect_heavy_equipment(frame, results)
        elif self.model_name == "Proximity":
            result = detect_proximity(frame, results)
        else:
            log_event(logger, "error", f"Model name '{self.model_name}' is not recognized.", event_type="error")
            raise ValueError(f"Unknown model name: {self.model_name}")

        final_status = result[0]
        reasons = result[1] if len(result) > 1 else []
        bboxes = result[2] if len(result) > 2 else None

        # return frame, final_status, [reasons], bboxes
        return frame, final_status, reasons, bboxes
