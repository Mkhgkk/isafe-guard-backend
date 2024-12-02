import os 
import sys
import time
import signal
import logging
import psutil
import GPUtil
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from main import create_app
from main.stream.model import Stream
from socket_.socketio_instance import socketio

logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)

stream_docs = {}

def get_system_utilization():
    """Function to fetch CPU and GPU utilization and emit to frontend."""
    cpu_usage = psutil.cpu_percent(interval=0)
    
    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0
    
    socketio.emit('system_status', {'cpu': cpu_usage, 'gpu': gpu_usage}, namespace='/video')


if __name__ == "__main__":
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