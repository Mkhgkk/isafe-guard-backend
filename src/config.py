"""
DEPRECATED: This file is kept for backward compatibility.
Please use utils.config_loader instead.

Example:
    from utils.config_loader import config
    frame_width = config.get('processing.frame_width')
"""
import os
from utils.config_loader import config

# Backward compatibility - all values now come from config.yaml
DEFAULT_PRECISION = config.get("detection.default_precision", "fp16")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = config.get("directories.static_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "main/static")))
ASSETS_DIR = config.get("directories.assets_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "assets")))
MODELS_DIR = config.get("directories.models_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "models")))

FRAME_WIDTH = config.get("processing.frame_width", 1280)
FRAME_HEIGHT = config.get("processing.frame_height", 720)

RECONNECT_WAIT_TIME_IN_SECS = config.get("processing.reconnect_wait_time_secs", 2)

WATCH_NOTIFICATION_URL = config.get("notifications.watch.url", "")

RECEIVER_EMAILS = config.get("notifications.email.receivers", [])
SENDER_EMAIL = config.get("notifications.email.sender", "")
EMAIL_PASSWORD = config.get("notifications.email.password", "")

TRITON_SERVER_URL = config.get("detection.triton.server_url", "http://tritonserver:8000")
