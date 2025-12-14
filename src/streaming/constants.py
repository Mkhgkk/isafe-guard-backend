from utils.config_loader import config

# Streaming configuration
RTMP_MEDIA_SERVER = config.get("streaming.rtmp_server")
NAMESPACE = "/default"

# Frame processing constants
DEFAULT_FRAME_TIMEOUT = config.get("gstreamer.default_frame_timeout")
DEFAULT_RECORD_DURATION = config.get("events.default_record_duration")
DEFAULT_FRAME_INTERVAL = 30
DEFAULT_UNSAFE_RATIO_THRESHOLD = config.get("events.unsafe_ratio_threshold")
DEFAULT_EVENT_COOLDOWN = config.get("events.event_cooldown")
MAX_RECONNECT_WAIT = config.get("gstreamer.max_reconnect_wait")
MAX_BUFFER_SIZE = config.get("gstreamer.max_buffers")
MAX_FRAME_QUEUE_SIZE = config.get("gstreamer.max_frame_queue_size")
FPS_QUEUE_SIZE = config.get("gstreamer.fps_queue_size")
INFERENCE_INTERVAL = config.get("processing.inference_interval")
