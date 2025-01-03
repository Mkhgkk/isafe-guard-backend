#!/usr/bin/env python
import os 
import signal
import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from main import create_app
from main.stream.model import Stream
from startup import configure_models, get_system_utilization

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

stream_docs = {}

if __name__ == "__main__":
  configure_models()
  logger.info("Models successfully configured!")

  # TODO:
  # asyncio should run after app has started because of socket connection

  logging.info("App starting...")

  app = create_app()

  with app.app_context():
        asyncio.run(Stream.start_active_streams_async())

  scheduler = BackgroundScheduler()
  if not scheduler.running:
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    scheduler.start()
  
  app.run(host=app.config["FLASK_DOMAIN"], port=app.config["FLASK_PORT"], debug=False, use_reloader=False, threaded=True)

  def handle_exit(signum, frame):
    print("Received termination signal. Shutting down...")
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        
    except Exception as e:
        print(f"Error during shutdown: {e}")
    finally:
        # Force exit
        os._exit(0)

  signal.signal(signal.SIGINT, handle_exit)
  signal.signal(signal.SIGTERM, handle_exit)