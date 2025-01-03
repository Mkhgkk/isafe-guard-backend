import os
import sys
import logging
import requests
import psutil
import GPUtil
from ultralytics import YOLO
from socket_.socketio_instance import socketio
from config import MODEL_REPOSITORY_URL, DEFAULT_PRECISION

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../models'))

def configure_models(precision=DEFAULT_PRECISION):
    """
      - Check if .pt models exist; if not download the models
      - Check respective precision directory for .engine model; if not export .engine
    """
    models = ['ppe', 'cutting_welding', 'fire_smoke', 'ladder', 'mobile_scaffolding', 'scaffolding']

    for model in models:
        model_dir = os.path.join(MODELS_DIR, model)
        model_path = os.path.join(model_dir, 'model.pt')

        # Create model directory if it does not exist
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        # Check if the .pt file exists, if not, download it
        if not os.path.isfile(model_path):
            model_url = f"{MODEL_REPOSITORY_URL}/{model}/model.pt"
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
                sys.exit(1)

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
                logger.info(f"Model {model}@{precision} exported and moved to {target_engine_path} successfully.")
            else:
                logger.error(f"Failed to export {model}@{precision} to TensorRT engine format.")
                sys.exit(1)


def get_system_utilization():
    """Function to fetch CPU and GPU utilization and emit to frontend."""
    cpu_usage = psutil.cpu_percent(interval=0)
    
    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0
    
    socketio.emit('system_status', {'cpu': cpu_usage, 'gpu': gpu_usage}, namespace='/video')

        