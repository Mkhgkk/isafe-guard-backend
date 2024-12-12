#!/usr/bin/env python
import os 
import sys
import time
import signal
import logging
import psutil
import GPUtil
import asyncio
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from main import create_app
from main.stream.model import Stream
from socket_.socketio_instance import socketio

from ultralytics import YOLO

MODEL_REPOSITORY_URL = "https://storage.googleapis.com/isafe-models"

logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)

stream_docs = {}

def get_system_utilization():
    """Function to fetch CPU and GPU utilization and emit to frontend."""
    cpu_usage = psutil.cpu_percent(interval=0)
    
    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0
    
    socketio.emit('system_status', {'cpu': cpu_usage, 'gpu': gpu_usage}, namespace='/video')

def configure_models(precision="fp16"):
    """
      - Check if .pt models exist; if not download the models
      - Check respective precision directory for .engine model; if not export .engine
    """
    models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'models'))
    models = ['ppe', 'cutting_welding', 'fire_smoke', 'ladder', 'mobile_scaffolding', 'scaffolding']

    for model in models:
        model_dir = os.path.join(models_dir, model)
        model_path = os.path.join(model_dir, 'model.pt')

        # Create model directory if it does not exist
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        # Check if the .pt file exists, if not, download it
        if not os.path.isfile(model_path):
            model_url = f"{MODEL_REPOSITORY_URL}/isafe-models/{model}/model.pt"
            try:
                print(f"Downloading {model} model from {model_url}...")
                response = requests.get(model_url, stream=True)
                response.raise_for_status()
                
                with open(model_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
                print(f"Successfully downloaded {model} model to {model_path}")
            except requests.exceptions.RequestException as e:
                print(f"Failed to download {model} model: {e}")

        # Check respective precision directory for .engine model
        engine_dir = os.path.join(model_dir, precision)
        engine_path = os.path.join(engine_dir, 'model.engine')

        if not os.path.exists(engine_dir):
            os.makedirs(engine_dir)    

        if not os.path.isfile(engine_path):
            print(f"Loading model: {model_path}")
    
            model_instance = YOLO(model_path, task="detect")

            # Export the model to TensorRT format with specified parameters
            print(f"Exporting model: {model_path} to TensorRT format")
            exported_engine_path = model_instance.export(
                format="engine",  
                half=True,         
                imgsz=640,
            )
            
            # Move exported engine file to engine directory
            if exported_engine_path and os.path.isfile(exported_engine_path):
                target_engine_path = os.path.join(engine_dir, 'model.engine')
                os.rename(exported_engine_path, target_engine_path)
                print(f"Model {model}@{precision} exported and moved to {target_engine_path} successfully.")
            else:
                print(f"Failed to export {model}@{precision} to TensorRT engine format.")
            


if __name__ == "__main__":
  configure_models()
  
  # TODO:
  # asyncio should run after app has started because of socket connection

  logging.info("App starting...")
  # TODO:
  # Check if .engine model exist or terminate if the models dont exist

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