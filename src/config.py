import os

DEFAULT_PRECISION = 'fp16'
MODEL_REPOSITORY_URL = "https://storage.googleapis.com/isafe-models"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'main/static'))
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'models'))

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

RECONNECT_WAIT_TIME_IN_SECS = 5