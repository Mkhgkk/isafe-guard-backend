import os

DEFAULT_PRECISION = "fp16"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "main/static"))
ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets"))
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models"))

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

# FRAME_WIDTH = 1920
# FRAME_HEIGHT = 1080

RECONNECT_WAIT_TIME_IN_SECS = 2

WATCH_NOTIFICATION_URL = "http://118.67.143.38:7000/external/camera"

# RECEIVER_EMAILS = ["emmachalz745@outlook.com"]
RECEIVER_EMAILS = []
SENDER_EMAIL = "contilabcau@gmail.com"
EMAIL_PASSWORD = "lbzf dykm dvgz yzuk"

TRITON_SERVER_URL = "http://tritonserver:8000"
