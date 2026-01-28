from utils.logging_config import get_logger, log_event
from utils.database_log_handler import setup_database_logging
from utils.go2rtc_sync import sync_streams_to_go2rtc
from apscheduler.schedulers.background import BackgroundScheduler #pyright: ignore[reportMissingImports]
from main.stream.model import Stream
from startup import (
    configure_detection_models,
    get_system_utilization,
    configure_matching_models,
)
from detection.kdl_detector import initialize_kdl_client
from detection.kdl import handle_kdl_result
from config import KDL_SERVER_URL, KDL_SERVER_PORT

# Logging configuration moved to utils/logging_config.py
# These specific logger level settings are now handled in setup_logging()

logger = get_logger(__name__)

scheduler = None

def create_app_services(app):
    global scheduler

    log_event(logger, "info", "Configuring models...", event_type="info")
    configure_detection_models()
    configure_matching_models()
    log_event(logger, "info", "Models successfully configured!", event_type="info")

    log_event(logger, "info", "Initializing KDL WebSocket client...", event_type="info")
    kdl_client = initialize_kdl_client(KDL_SERVER_URL, KDL_SERVER_PORT)

    # Set up result callback - need to track which stream_id sent each frame
    # For now, we'll use a simple approach where results are broadcast to all KDL streams
    # TODO: Implement proper stream_id tracking if needed
    def kdl_result_callback(metadata, image_bytes):
        # Extract stream_id from metadata if available, otherwise use default
        stream_id = metadata.get("stream_id", "default")
        handle_kdl_result(metadata, image_bytes, stream_id)

    kdl_client.set_result_callback(kdl_result_callback)
    log_event(logger, "info", "KDL WebSocket client initialized!", event_type="info")

    log_event(logger, "info", "Starting async stream tasks...", event_type="info")
    with app.app_context():
        Stream.start_active_streams()

    log_event(logger, "info", "Starting background scheduler...", event_type="info")
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    scheduler.start()
    
    # Setup database logging with new simplified handler
    log_event(logger, "info", "Setting up database logging...", event_type="service_init")
    success = setup_database_logging()
    if success:
        log_event(logger, "info", "Database logging setup complete!", event_type="service_init")
    else:
        log_event(logger, "warning", "Database logging setup failed", event_type="service_init")

    # Sync database streams to go2rtc configuration
    log_event(logger, "info", "Syncing database streams to go2rtc...", event_type="service_init")
    sync_result = sync_streams_to_go2rtc()
    if sync_result["status"] == "success":
        log_event(logger, "info", f"go2rtc sync complete: {sync_result['message']}", event_type="service_init")
    elif sync_result["status"] == "skipped":
        log_event(logger, "info", f"go2rtc sync skipped: {sync_result['message']}", event_type="service_init")
    else:
        log_event(logger, "warning", f"go2rtc sync failed: {sync_result['message']}", event_type="service_init")
