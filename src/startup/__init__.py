import os
import sys
from utils.logging_config import get_logger, log_event
from utils.config_loader import config
import psutil
import GPUtil
from ultralytics import YOLO
from events import emit_event, EventType

logger = get_logger(__name__)

USE_NPU = config.get("detection.npu.enabled", False)
DEFAULT_PRECISION = config.get("detection.default_precision", "fp16")
BASE_DIR = config.get("directories.base_dir", "src")

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
    return
    """
    - Check if .pt models exist; if not download the models
    - Check respective precision directory for .engine model; if not export .engine
    """
    if USE_NPU:
        # Do some setup for NPU if needed i.e. exit program if weights are not configured properly etc.
        log_event(
            logger,
            "info",
            "NPU is enabled. Skipping TensorRT engine export.",
            event_type="info",
        )
        return

    models = [
        "ppe/v1/640L",
        "ppe_aerial/v1/640L",
        "cutting_welding/v1/640L",
        "fire_smoke/v1/640L",
        "ladder/v1/640L",
        "mobile_scaffolding/v1/640L",
        "scaffolding/v1/1280L",
        "heavy_equipment/v2/1280L",
        "proximity/v1/640L",
        "approtium/v1/1280L",
        "nexilis_proximity/v2/1280L",
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

            log_event(
                logger,
                "info",
                f"Exporting model: {model_path} to TensorRT format",
                event_type="info",
            )
            exported_engine_path = model_instance.export(
                format="engine",
                half=True if precision == "fp16" else False,
                # imgsz=640,
                imgsz=1280,
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
        broadcast=True,
    )
