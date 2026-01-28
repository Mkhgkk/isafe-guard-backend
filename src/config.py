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


# Helper function to resolve directory paths to absolute paths
def _resolve_dir_path(path_from_config, fallback_relative_path):
    """Convert a config path to absolute path."""
    if path_from_config and os.path.isabs(path_from_config):
        return path_from_config
    # If relative, resolve from BASE_DIR (src directory)
    relative_path = path_from_config or fallback_relative_path
    return os.path.abspath(os.path.join(BASE_DIR, relative_path))


STATIC_DIR = _resolve_dir_path(config.get("directories.static_dir"), "main/static")
ASSETS_DIR = _resolve_dir_path(config.get("directories.assets_dir"), "assets")
MODELS_DIR = _resolve_dir_path(config.get("directories.models_dir"), "models")

FRAME_WIDTH = config.get("processing.frame_width", 1280)
FRAME_HEIGHT = config.get("processing.frame_height", 720)

TRITON_SERVER_URL = "http://tritonserver:8000"

# KDL WebSocket Server Configuration
KDL_SERVER_URL = os.getenv("KDL_SERVER_URL", "172.17.0.1")
KDL_SERVER_PORT = int(os.getenv("KDL_SERVER_PORT", "12321"))
RECONNECT_WAIT_TIME_IN_SECS = config.get("processing.reconnect_wait_time_secs", 2)

WATCH_NOTIFICATION_URL = config.get("notifications.watch.url", "")

RECEIVER_EMAILS = config.get("notifications.email.receivers", [])
SENDER_EMAIL = config.get("notifications.email.sender", "")
EMAIL_PASSWORD = config.get("notifications.email.password", "")

TRITON_SERVER_URL = config.get(
    "detection.triton.server_url", "http://tritonserver:8000"
)
