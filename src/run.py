from main import create_app
import logging
import time
import sys
import os 
import signal

from appwrite.client import Client
from appwrite.query import Query
from appwrite.services.databases import Databases
from appwrite.id import ID

import asyncio

from main.stream.model import Stream

from database import get_database_instance

import psutil
import GPUtil
from apscheduler.schedulers.background import BackgroundScheduler

from socket_.socketio_instance import socketio

import logging

# from main.shared import streams

logging.getLogger('apscheduler').setLevel(logging.WARNING)

stream_docs = {}

databases = get_database_instance()

def get_system_utilization():
    """Function to fetch CPU and GPU utilization and emit to frontend."""
    cpu_usage = psutil.cpu_percent(interval=0)
    
    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0
    
    socketio.emit('system_status', {'cpu': cpu_usage, 'gpu': gpu_usage}, namespace='/video')


def fetch_streams():
  streams = databases.list_documents(
    database_id="isafe-guard-db",
    collection_id="66f504260003d64837e5",
  )

  for stream in  streams['documents']:
    stream_docs[stream["stream_id"]] = stream

async def fetch_schedules():
  tasks = []

  schedules = databases.list_documents(
    database_id="isafe-guard-db",
    collection_id="66fa20d600253c7d4503",
    queries=[Query.greater_than('end_timestamp', int(time.time()))]
  )

  for schedule in schedules['documents']:
    # active schedules
    if schedule["start_timestamp"] < int(time.time()):

      # if schedule['stream_id'] != 'stream1':
      #   continue
      
      print(schedule)
      stream = stream_docs[schedule['stream_id']]
     
      task = Stream.start_stream(stream['rtsp_link'], schedule['model_name'], stream['stream_id'], schedule['end_timestamp'], stream['cam_ip'], stream['ptz_port'], stream['ptz_username'], stream['ptz_password'])
      tasks.append(task)

  await asyncio.gather(*tasks)



if __name__ == "__main__":
  # TODO:
  # asyncio should run after app has started because of socket connection

  fetch_streams()
  print("app starting...")
  asyncio.run(fetch_schedules())
  app = create_app()
  app.databases = databases

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
        # for stream_id, video_stream in streams.items():
        #     video_stream.stop_stream()
        pass
    except Exception as e:
        print(f"Error during shutdown: {e}")
    finally:
        # Force exit
        os._exit(0)

  signal.signal(signal.SIGINT, handle_exit)
  signal.signal(signal.SIGTERM, handle_exit)