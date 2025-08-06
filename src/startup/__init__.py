import os
import sys
from utils.logging_config import get_logger, log_event
import psutil
import GPUtil
from ultralytics import YOLO
from events import emit_event, EventType
from config import DEFAULT_PRECISION, BASE_DIR

logger = get_logger(__name__)

MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models"))
NAMESPACE = "/default"


def configure_matching_models():
    models = [
        "superglue_indoor.pth",
        "superglue_outdoor.pth",
        "superpoint_v1.pth",
    ]

    for model in models:
        model_dir = os.path.join(BASE_DIR, "intrusion", "models", "weights")
        model_path = os.path.join(model_dir, model)

        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"The model file '{model_path}' was not found.")


def configure_detection_models(precision=DEFAULT_PRECISION):
    """
    - Check if .pt models exist; if not download the models
    - Check respective precision directory for .engine model; if not export .engine
    """
    models = [
        "ppe",
        "ppe_aerial",
        "cutting_welding",
        "fire_smoke",
        "ladder",
        "mobile_scaffolding",
        "scaffolding",
        "heavy_equipment"
    ]

    for model in models:
        model_dir = os.path.join(MODELS_DIR, model)
        model_path = os.path.join(model_dir, "model.pt")

        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"The model file '{model_path}' was not found.")

        engine_dir = os.path.join(model_dir, precision)
        engine_path = os.path.join(engine_dir, "model.engine")

        if not os.path.exists(engine_dir):
            os.makedirs(engine_dir)

        if not os.path.isfile(engine_path):
            log_event(logger, "info", f"Loading model: {model_path}", event_type="info")

            model_instance = YOLO(model_path, task="detect")

            log_event(logger, "info", f"Exporting model: {model_path} to TensorRT format", event_type="info")
            exported_engine_path = model_instance.export(
                format="engine",
                half= True if precision == "fp16" else False,
                imgsz=640,
                dynamic=True,
                # nms=True,
                # conf=0.6,
                # iou=0.45,
                # agnostic_nms=True,  
            )

            if exported_engine_path and os.path.isfile(exported_engine_path):
                target_engine_path = os.path.join(engine_dir, "model.engine")
                os.rename(exported_engine_path, target_engine_path)
                logger.info(
                    f"Model {model}@{precision} exported and moved to {target_engine_path} successfully."
                )
            else:
                logger.error(
                    f"Failed to export {model}@{precision} to TensorRT engine format."
                )
                sys.exit(1)


def get_system_utilization():
    cpu_usage = psutil.cpu_percent(interval=0)

    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0

    emit_event(
        event_type=EventType.SYSTEM_STATUS,
        data={"cpu": cpu_usage, "gpu": gpu_usage},
        broadcast=True 
    )
