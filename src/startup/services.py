import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from main.stream.model import Stream
from startup import (
    configure_detection_models,
    get_system_utilization,
    configure_matching_models,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("ultralytics").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

scheduler = None

def create_app_services(app):
    global scheduler

    logger.info("Configuring models...")
    configure_detection_models()
    configure_matching_models()
    logger.info("Models successfully configured!")

    logger.info("Starting async stream tasks...")
    with app.app_context():
        asyncio.run(Stream.start_active_streams_async())

    logger.info("Starting background scheduler...")
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    scheduler.start()
