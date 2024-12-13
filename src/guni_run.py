#!/usr/bin/env python
import os 
import signal
import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from main import create_app
from main.stream.model import Stream
from startup import configure_models, get_system_utilization

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Global objects (these will live throughout the app's lifecycle)
scheduler = None  # To be initialized later
stream_docs = {}

# Create app
app = create_app()

def start_background_tasks():
    """
    This function will start background tasks for models, streaming, and scheduling.
    """
    # 1. Configure models
    configure_models()
    logger.info("Models successfully configured!")

    # 2. Start async streams
    try:
        with app.app_context():
            asyncio.run(Stream.start_active_streams_async())
    except Exception as e:
        logger.error(f"Error starting async streams: {e}")

    # 3. Start the scheduler
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    scheduler.start()
    logger.info("Scheduler started successfully.")

def handle_exit(signum, frame):
    """
    Gracefully handle termination signals.
    """
    logger.info("Received termination signal. Shutting down...")
    try:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    finally:
        # Force exit
        os._exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# Start background tasks after the app is created
start_background_tasks()
