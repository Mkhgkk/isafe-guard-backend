from utils.logging_config import get_logger, log_event
from apscheduler.schedulers.background import BackgroundScheduler #pyright: ignore[reportMissingImports]
from main.stream.model import Stream
from startup import (
    configure_detection_models,
    get_system_utilization,
    configure_matching_models,
)

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

    log_event(logger, "info", "Starting async stream tasks...", event_type="info")
    with app.app_context():
        Stream.start_active_streams()

    log_event(logger, "info", "Starting background scheduler...", event_type="info")
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    scheduler.start()
