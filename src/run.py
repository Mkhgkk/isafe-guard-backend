#!/usr/bin/env python
import os
import signal
import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from main import create_app
from main.stream.model import Stream
from startup import (
    configure_detection_models,
    get_system_utilization,
    configure_matching_models,
)
from startup.services import create_app_services

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

if __name__ == "__main__":
    app = create_app()
    create_app_services(app)
    app.run(
        host=app.config["FLASK_DOMAIN"],
        port=app.config["FLASK_PORT"],
        debug=False,
        use_reloader=False,
        threaded=True,
    )

    # def handle_exit(signum, frame):
    #     logging.info("Received termination signal. Shutting down...")
    #     try:
    #         if scheduler.running:
    #             scheduler.shutdown(wait=False)

    #     except Exception as e:
    #         logging.error(f"Error during shutdown: {e}")
    #     finally:
    #         os._exit(0)

    # signal.signal(signal.SIGINT, handle_exit)
    # signal.signal(signal.SIGTERM, handle_exit)
