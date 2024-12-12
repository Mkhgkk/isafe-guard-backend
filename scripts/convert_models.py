#!/usr/bin/env python
import os
import requests
from ultralytics import YOLO

model_urls = {
    "PPEbest.pt": "https://storage.googleapis.com/isafe-models/PPEbest.pt"
}

# models_dir = "models"
models_dir = video_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/models'))
os.makedirs(models_dir, exist_ok=True)

for model_name, url in model_urls.items():
    model_path = os.path.join(models_dir, model_name)
    if not os.path.exists(model_path):
        print(f"Downloading {model_name} from {url}")
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(model_path, "wb") as f:
                f.write(response.content)
            print(f"{model_name} downloaded successfully.")
        else:
            print(f"Failed to download {model_name}. Status code: {response.status_code}")
    else:
        print(f"{model_name} already exists. Skipping download.")

for model_file in model_urls.keys():
    print(f"Loading model: {model_file}")
    
    model = YOLO(os.path.join(models_dir, model_file), task="detect")

    # Export the model to TensorRT format with specified parameters
    print(f"Exporting model: {model_file} to TensorRT format")
    model.export(
        format="engine",  # Export to TensorRT format
        # int8=True,        # Enable int8 precision
        half=True,         # Enable half precision (FP16)
        # Uncomment the following lines to set other options as needed
        # dynamic=True,    # Enable dynamic shape
        imgsz=640,
        # batch=8,         # Batch size
        # workspace=4,     # Workspace size in GB
        # device=1         # Specify the GPU device if necessary
    )
    print(f"Model {model_file} exported successfully.\n")


