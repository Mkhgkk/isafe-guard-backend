from main import create_app
import logging
import time

from appwrite.client import Client
from appwrite.query import Query
from appwrite.services.databases import Databases
from appwrite.id import ID

import asyncio

from main.stream.model import Stream

import psutil
import GPUtil
from apscheduler.schedulers.background import BackgroundScheduler

from socket_.socketio_instance import socketio

import logging

logging.getLogger('apscheduler').setLevel(logging.WARNING)

client = Client()
# client.set_endpoint('http://192.168.0.10/v1')
client.set_endpoint('http://172.105.209.31/v1')
client.set_project('66f4c2e6001ef89c0f5c')
# client.set_key('standard_f6ffca3b91315e5263932317123368335466126c2bb58bf4201b64c9c3768ab3f364eabe0f7ba852fa24876c624393b306ce9a3f71db9c8fa951526a39e49721c80812d477196faad02d282ea51962a823c02f4580c1c95c67e6dba054653fa4d094a99ce4cb1a31ce52c57dbda6b925168446dd879de1e1d6321f0fa2f88cbd')
client.set_key('standard_a5d6a12567fad8968cf5e2bc4482006c886d22e175e2d9bdabfea4453958462e507effc6276fc3f9b6f766bf34bf5290a9cb56d8277003a4128de039fd5a5d7299c12ea831eccc96d04c50655e5f0a7df0a5fcd80532a664649f0fb9e34cdfe33f12d91035738668f6b2bbefb7ed665c8905eb0796038981498cd4e7a9bc22aa')

databases = Databases(client)

stream_docs = {}

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
  print(int(time.time()))
  fetch_streams()
  # fetch_schedules()
  asyncio.run(fetch_schedules())
  app = create_app()
  app.databases = databases

  scheduler = BackgroundScheduler()
  scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
  scheduler.start()
  
  app.run(host=app.config["FLASK_DOMAIN"], port=app.config["FLASK_PORT"])
else:
  logging.basicConfig(app.config["FLASK_DIRECTORY"] + "trace.log", level=logging.DEBUG)