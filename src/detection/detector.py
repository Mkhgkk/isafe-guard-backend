import os
import cv2
import time
from utils.logging_config import get_logger, log_event
import datetime
import numpy as np
from typing import List, Optional, Tuple
from ultralytics import YOLO
from detection.npu_inference import NPUInferenceEngine, InferenceConfig, Detection

USE_NPU = os.getenv("USE_NPU", "false").lower() == "true"

from sahi.models.ultralytics import UltralyticsDetectionModel
from sahi.predict import get_sliced_prediction

SAHI_AVAILABLE = True

logger = get_logger(__name__)
from detection.ppe import detect_ppe
from detection.scaffolding import detect_scaffolding
from detection.mobile_scaffolding import detect_mobile_scaffolding
from detection.ladder import detect_ladder
from detection.cutting_welding import detect_cutting_welding
from detection.fire_smoke import detect_fire_smoke
from detection.heavy_equipment import detect_heavy_equipment
from detection.proximity import detect_proximity
from detection.approtium import detect_approtium
from ultralytics.engine.results import Results

from config import DEFAULT_PRECISION

MODELS_PATH = video_directory = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../models")
)


npu_engine = None

if USE_NPU:

    config = InferenceConfig(
                    model_path=os.path.join(MODELS_PATH, f"yolov8s_best_globalCore_v1.mxq"),
                    img_size=(640, 640),
                    # num_classes=17,
                    conf_threshold=0.5,
                    iou_threshold=0.5,
                    use_global8_core=True,  # Use all 8 NPU cores
                    device_id=0  # Use first NPU device
                )

    engine = NPUInferenceEngine(config)
    engine.initialize()
    npu_engine = engine

class Detector:
    def __init__(
        self,
        model_name: str,
        use_sahi: bool = False,

        slice_height: int = 640,
        slice_width: int = 640,
        overlap_height_ratio: float = 0.3,
        overlap_width_ratio: float = 0.3,
        confidence_threshold: float = 0.25,
    ) -> None:
        self.model_name = model_name
        self.use_sahi = use_sahi and SAHI_AVAILABLE
        self.slice_height = slice_height
        self.slice_width = slice_width
        self.overlap_height_ratio = overlap_height_ratio
        self.overlap_width_ratio = overlap_width_ratio
        self.confidence_threshold = confidence_threshold

        self.npu_engine = None


        if USE_NPU:
            log_event(
                logger,
                "info",
                "NPU is enabled. Using NPU for inference.",
                event_type="info",
            )
        else:    
            if self.use_sahi:
                if not SAHI_AVAILABLE:
                    log_event(
                        logger,
                        "warning",
                        "SAHI not available, falling back to standard detection",
                        event_type="warning",
                    )
                    self.use_sahi = False
                self.model = self._load_sahi_model()
            else:
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
            "Ladder": os.path.join(
                MODELS_PATH, f"ladder/{DEFAULT_PRECISION}/model.engine"
            ),
            "MobileScaffolding": os.path.join(
                MODELS_PATH, f"mobile_scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Scaffolding": os.path.join(
                MODELS_PATH, f"scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "CuttingWelding": os.path.join(
                MODELS_PATH, f"cutting_welding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Fire": os.path.join(
                MODELS_PATH, f"fire_smoke/{DEFAULT_PRECISION}/model.engine"
            ),
            "HeavyEquipment": os.path.join(
                MODELS_PATH, f"heavy_equipment/{DEFAULT_PRECISION}/model.engine"
            ),
            "Proximity": os.path.join(
                MODELS_PATH, f"heavy_equipment/{DEFAULT_PRECISION}/model.engine"
            ),
            # "Proximity": os.path.join(MODELS_PATH, f"proximity/{DEFAULT_PRECISION}/model.engine"),
            "Approtium": os.path.join(
                MODELS_PATH, f"approtium/{DEFAULT_PRECISION}/model.engine"
            ),
        }

        model_path = model_paths.get(self.model_name)
        if not model_path:
            log_event(
                logger,
                "error",
                f"Model name '{self.model_name}' is not recognized.",
                event_type="error",
            )
            raise ValueError(f"Unknown model name: {self.model_name}")

        log_event(
            logger, "info", f"Loading model: {self.model_name}", event_type="info"
        )
        return YOLO(model_path)

    def _load_sahi_model(self) -> UltralyticsDetectionModel:
        """
        Load SAHI detection model
        :raises ValueError: If the model name is not recognized.
        """
        model_paths = {
            "PPE": os.path.join(MODELS_PATH, f"ppe/{DEFAULT_PRECISION}/model.engine"),
            "PPEAerial": os.path.join(
                MODELS_PATH, f"ppe_aerial/{DEFAULT_PRECISION}/model.engine"
            ),
            "Ladder": os.path.join(
                MODELS_PATH, f"ladder/{DEFAULT_PRECISION}/model.engine"
            ),
            "MobileScaffolding": os.path.join(
                MODELS_PATH, f"mobile_scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Scaffolding": os.path.join(
                MODELS_PATH, f"scaffolding/{DEFAULT_PRECISION}/model.engine"
            ),
            "CuttingWelding": os.path.join(
                MODELS_PATH, f"cutting_welding/{DEFAULT_PRECISION}/model.engine"
            ),
            "Fire": os.path.join(
                MODELS_PATH, f"fire_smoke/{DEFAULT_PRECISION}/model.engine"
            ),
            "HeavyEquipment": os.path.join(
                MODELS_PATH, f"heavy_equipment/{DEFAULT_PRECISION}/model.engine"
            ),
            "Proximity": os.path.join(
                MODELS_PATH, f"heavy_equipment/{DEFAULT_PRECISION}/model.engine"
            ),
            "Approtium": os.path.join(
                MODELS_PATH, f"approtium/{DEFAULT_PRECISION}/model.engine"
            ),
        }

        model_path = model_paths.get(self.model_name)
        if not model_path:
            log_event(
                logger,
                "error",
                f"Model name '{self.model_name}' is not recognized.",
                event_type="error",
            )
            raise ValueError(f"Unknown model name: {self.model_name}")

        log_event(
            logger, "info", f"Loading SAHI model: {self.model_name}", event_type="info"
        )
        return UltralyticsDetectionModel(
            model_path=model_path,
            confidence_threshold=self.confidence_threshold,
            device="cuda:0",
        )

    def detect(
        self, frame: np.ndarray
    ) -> Tuple["np.ndarray", str, List[str], Optional[List[Tuple[int, int, int, int]]]]:
        
        if USE_NPU:
            detections = npu_engine.detect(frame)
            # log_event(logger, "info", f"NPU detections: {detections}", event_type="npu_detections")
            # Convert NPU Detection objects to YOLO-like Results format
            mock_results = self._convert_npu_to_yolo_format(detections)
            return self._process_detections_with_mock_results(frame, mock_results)
        else:
            if self.use_sahi:
                return self._detect_with_sahi(frame)
            else:
                return self._detect_standard(frame)

    def _detect_standard(
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
        elif self.model_name == "Approtium":
            result = detect_approtium(frame, results)
        else:
            log_event(
                logger,
                "error",
                f"Model name '{self.model_name}' is not recognized.",
                event_type="error",
            )
            raise ValueError(f"Unknown model name: {self.model_name}")

        final_status = result[0]
        reasons = result[1] if len(result) > 1 else []
        bboxes = result[2] if len(result) > 2 else None

        return frame, final_status, reasons, bboxes

    def _convert_sahi_to_yolo_format(self, sahi_results, frame_shape):
        """
        Convert SAHI results to YOLO-like Results format for compatibility
        """
        import torch

        # Extract predictions from SAHI results
        predictions = sahi_results.object_prediction_list

        if not predictions:
            # Return empty results in YOLO format
            empty_tensor = torch.empty((0, 4))
            mock_boxes = type("MockBoxes", (), {})()
            mock_boxes.xyxy = empty_tensor
            mock_boxes.conf = torch.empty(0)
            mock_boxes.cls = torch.empty(0)
            mock_boxes.data = torch.empty(
                (0, 6)
            )  # Add data attribute [x1,y1,x2,y2,conf,cls]

            mock_result = type("MockResult", (), {})()
            mock_result.boxes = mock_boxes
            mock_result.names = {}
            return [mock_result]

        # Convert SAHI predictions to tensors
        boxes = []
        confidences = []
        class_ids = []
        class_names = {}

        for pred in predictions:
            bbox = pred.bbox.to_voc_bbox()  # x1, y1, x2, y2
            boxes.append(bbox)
            confidences.append(pred.score.value)
            class_ids.append(pred.category.id)
            class_names[pred.category.id] = pred.category.name

        # Create tensors
        boxes_tensor = torch.tensor(boxes, dtype=torch.float32)
        conf_tensor = torch.tensor(confidences, dtype=torch.float32)
        cls_tensor = torch.tensor(class_ids, dtype=torch.float32)

        # Create data tensor combining boxes, conf, and cls
        data_tensor = torch.cat(
            [boxes_tensor, conf_tensor.unsqueeze(1), cls_tensor.unsqueeze(1)], dim=1
        )

        # Create mock YOLO Results object
        mock_boxes = type("MockBoxes", (), {})()
        mock_boxes.xyxy = boxes_tensor
        mock_boxes.conf = conf_tensor
        mock_boxes.cls = cls_tensor
        mock_boxes.data = data_tensor

        mock_result = type("MockResult", (), {})()
        mock_result.boxes = mock_boxes
        mock_result.names = class_names

        return [mock_result]

    def _convert_npu_to_yolo_format(self, detections: List[Detection]):
        """
        Convert NPU Detection objects to YOLO-like Results format for compatibility
        """
        import torch

        if not detections:
            # Return empty results in YOLO format
            empty_tensor = torch.empty((0, 4))
            mock_boxes = type("MockBoxes", (), {})()
            mock_boxes.xyxy = empty_tensor
            mock_boxes.conf = torch.empty(0)
            mock_boxes.cls = torch.empty(0)
            mock_boxes.data = torch.empty((0, 6))  # [x1,y1,x2,y2,conf,cls]

            mock_result = type("MockResult", (), {})()
            mock_result.boxes = mock_boxes
            mock_result.names = {}
            return [mock_result]

        # Convert NPU Detection objects to tensors
        boxes = []
        confidences = []
        class_ids = []
        class_names = {}

        for detection in detections:
            bbox = [detection.x1, detection.y1, detection.x2, detection.y2]
            boxes.append(bbox)
            confidences.append(detection.confidence)
            class_ids.append(detection.class_id)
            if detection.class_name:
                class_names[detection.class_id] = detection.class_name

        # Create tensors
        boxes_tensor = torch.tensor(boxes, dtype=torch.float32)
        conf_tensor = torch.tensor(confidences, dtype=torch.float32)
        cls_tensor = torch.tensor(class_ids, dtype=torch.float32)

        # Create data tensor combining boxes, conf, and cls
        data_tensor = torch.cat(
            [boxes_tensor, conf_tensor.unsqueeze(1), cls_tensor.unsqueeze(1)], dim=1
        )

        # Create mock YOLO Results object
        mock_boxes = type("MockBoxes", (), {})()
        mock_boxes.xyxy = boxes_tensor
        mock_boxes.conf = conf_tensor
        mock_boxes.cls = cls_tensor
        mock_boxes.data = data_tensor

        mock_result = type("MockResult", (), {})()
        mock_result.boxes = mock_boxes
        mock_result.names = class_names

        return [mock_result]

    def _process_detections_with_mock_results(
        self, frame: np.ndarray, mock_results
    ) -> Tuple["np.ndarray", str, List[str], Optional[List[Tuple[int, int, int, int]]]]:
        """Process detections using the appropriate detection function with mock YOLO results"""
        final_status: str = "Safe"
        reasons: List[str] = []
        bboxes: Optional[List[Tuple[int, int, int, int]]] = None

        if self.model_name in ["PPE", "PPEAerial"]:
            result = detect_ppe(frame, mock_results)
        elif self.model_name == "Ladder":
            result = detect_ladder(frame, mock_results)
        elif self.model_name == "MobileScaffolding":
            result = detect_mobile_scaffolding(frame, mock_results)
        elif self.model_name == "Scaffolding":
            result = detect_scaffolding(frame, mock_results)
        elif self.model_name == "Fire":
            result = detect_fire_smoke(frame, mock_results)
        elif self.model_name == "CuttingWelding":
            result = detect_cutting_welding(frame, mock_results)
        elif self.model_name == "HeavyEquipment":
            result = detect_heavy_equipment(frame, mock_results)
        elif self.model_name == "Proximity":
            result = detect_proximity(frame, mock_results)
        elif self.model_name == "Approtium":
            result = detect_approtium(frame, mock_results)
        else:
            log_event(
                logger,
                "error",
                f"Model name '{self.model_name}' is not recognized.",
                event_type="error",
            )
            raise ValueError(f"Unknown model name: {self.model_name}")

        final_status = result[0]
        reasons = result[1] if len(result) > 1 else []
        bboxes = result[2] if len(result) > 2 else None

        return frame, final_status, reasons, bboxes

    def _detect_with_sahi(
        self, frame: np.ndarray
    ) -> Tuple["np.ndarray", str, List[str], Optional[List[Tuple[int, int, int, int]]]]:
        results = get_sliced_prediction(
            image=frame,
            detection_model=self.model,
            slice_height=self.slice_height,
            slice_width=self.slice_width,
            overlap_height_ratio=self.overlap_height_ratio,
            overlap_width_ratio=self.overlap_width_ratio,
            verbose=0,
        )

        # Convert SAHI results to YOLO-like format for compatibility
        mock_results = self._convert_sahi_to_yolo_format(results, frame.shape)

        final_status: str = "Safe"
        reasons: List[str] = []
        bboxes: Optional[List[Tuple[int, int, int, int]]] = None

        if self.model_name in ["PPE", "PPEAerial"]:
            result = detect_ppe(frame, mock_results)
        elif self.model_name == "Ladder":
            result = detect_ladder(frame, mock_results)
        elif self.model_name == "MobileScaffolding":
            result = detect_mobile_scaffolding(frame, mock_results)
        elif self.model_name == "Scaffolding":
            result = detect_scaffolding(frame, mock_results)
        elif self.model_name == "Fire":
            result = detect_fire_smoke(frame, mock_results)
        elif self.model_name == "CuttingWelding":
            result = detect_cutting_welding(frame, mock_results)
        elif self.model_name == "HeavyEquipment":
            result = detect_heavy_equipment(frame, mock_results)
        elif self.model_name == "Proximity":
            result = detect_proximity(frame, mock_results)
        elif self.model_name == "Approtium":
            result = detect_approtium(frame, mock_results)
        else:
            log_event(
                logger,
                "error",
                f"Model name '{self.model_name}' is not recognized.",
                event_type="error",
            )
            raise ValueError(f"Unknown model name: {self.model_name}")

        final_status = result[0]
        reasons = result[1] if len(result) > 1 else []
        bboxes = result[2] if len(result) > 2 else None

        return frame, final_status, reasons, bboxes

    def _convert_sahi_to_yolo_format(self, sahi_results, frame_shape):
        """
        Convert SAHI results to YOLO-like Results format for compatibility
        """
        import torch

        # Extract predictions from SAHI results
        predictions = sahi_results.object_prediction_list

        if not predictions:
            # Return empty results in YOLO format
            empty_tensor = torch.empty((0, 4))
            mock_boxes = type("MockBoxes", (), {})()
            mock_boxes.xyxy = empty_tensor
            mock_boxes.conf = torch.empty(0)
            mock_boxes.cls = torch.empty(0)
            mock_boxes.data = torch.empty(
                (0, 6)
            )  # Add data attribute [x1,y1,x2,y2,conf,cls]

            mock_result = type("MockResult", (), {})()
            mock_result.boxes = mock_boxes
            mock_result.names = {}
            return [mock_result]

        # Convert SAHI predictions to tensors
        boxes = []
        confidences = []
        class_ids = []
        class_names = {}

        for pred in predictions:
            bbox = pred.bbox.to_voc_bbox()  # x1, y1, x2, y2
            boxes.append(bbox)
            confidences.append(pred.score.value)
            class_ids.append(pred.category.id)
            class_names[pred.category.id] = pred.category.name

        # Create tensors
        boxes_tensor = torch.tensor(boxes, dtype=torch.float32)
        conf_tensor = torch.tensor(confidences, dtype=torch.float32)
        cls_tensor = torch.tensor(class_ids, dtype=torch.float32)

        # Create data tensor combining boxes, conf, and cls
        data_tensor = torch.cat(
            [boxes_tensor, conf_tensor.unsqueeze(1), cls_tensor.unsqueeze(1)], dim=1
        )

        # Create mock YOLO Results object
        mock_boxes = type("MockBoxes", (), {})()
        mock_boxes.xyxy = boxes_tensor
        mock_boxes.conf = conf_tensor
        mock_boxes.cls = cls_tensor
        mock_boxes.data = data_tensor

        mock_result = type("MockResult", (), {})()
        mock_result.boxes = mock_boxes
        mock_result.names = class_names

        return [mock_result]
