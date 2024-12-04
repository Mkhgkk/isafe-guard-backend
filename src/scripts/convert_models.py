import os
from ultralytics import YOLO

model_files = ["PPEbest.pt"]

# Loop through each model and export it
for model_file in model_files:
    print(f"Loading model: {model_file}")
    
    # Load the YOLOv8 model
    model = YOLO(os.path.join("models", model_file), task="detect")

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

