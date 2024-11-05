# import numpy as np
# import tritonclient.http as httpclient
# from PIL import Image

# # Load and preprocess the image
# image_path = "worker.jpeg"
# image = Image.open(image_path).resize((640, 640))
# image = np.array(image).astype(np.float32)
# image = np.transpose(image, (2, 0, 1))  # Convert to CHW format
# image = np.expand_dims(image, axis=0)  # Add batch dimension

# # Create Triton client
# url = "localhost:8000"
# model_name = "PPEbest"
# client = httpclient.InferenceServerClient(url=url)

# # Prepare inputs and outputs
# inputs = [httpclient.InferInput("images", image.shape, "FP32")]
# inputs[0].set_data_from_numpy(image)

# outputs = [httpclient.InferRequestedOutput("output0")]

# # Perform inference
# response = client.infer(model_name, inputs, outputs=outputs)

# # Get the output
# output_data = response.as_numpy("output0")
# print("Inference result:", output_data)


# import numpy as np
# import tritonclient.grpc as grpcclient
# from PIL import Image

# # Load and preprocess the image
# image_path = "worker.jpeg"
# image = Image.open(image_path).resize((640, 640))
# image = np.array(image).astype(np.float32)
# image = np.transpose(image, (2, 0, 1))  # Convert to CHW format
# image = np.expand_dims(image, axis=0)  # Add batch dimension

# # Create Triton gRPC client
# url = "localhost:8001"  # gRPC typically uses port 8001
# model_name = "PPEtrt" # .engine model
# # model_name = "PPEbest" # .onnx model
# client = grpcclient.InferenceServerClient(url=url)

# # Prepare inputs and outputs
# inputs = [grpcclient.InferInput("images", image.shape, "FP32")]
# inputs[0].set_data_from_numpy(image)

# outputs = [grpcclient.InferRequestedOutput("output0")]

# # Perform inference
# # response = client.infer(model_name, inputs, outputs=outputs)

# # Get the output
# output_data = response.as_numpy("output0")
# print("Inference result:", output_data)





# import numpy as np
# import tritonclient.http as httpclient
# from PIL import Image

# # Load and preprocess the image
# image_path = "worker.jpeg"
# image = Image.open(image_path).resize((640, 640))
# image = np.array(image).astype(np.float32) / 255.0
# image = np.transpose(image, (2, 0, 1))  # Convert to CHW format
# image = np.expand_dims(image, axis=0)  # Add batch dimension

# # Initialize Triton client
# url = "localhost:8000"
# model_name = "PPEbest"
# client = httpclient.InferenceServerClient(url=url)

# # Prepare the input and output
# inputs = [httpclient.InferInput("images", image.shape, "FP32")]
# inputs[0].set_data_from_numpy(image)

# outputs = [httpclient.InferRequestedOutput("output0")]

# # Perform inference
# results = client.infer(model_name, inputs, outputs=outputs)


# print(results)

# # Process the output
# output_data = results.as_numpy("output0")
# print("Output shape:", output_data.shape)
# print("Output data:", output_data)



# for detection in output_data:
#     x, y, w, h = detection[:4]  # Bounding box coordinates
#     conf = detection[4]  # Confidence score
#     class_id = detection[5]  # Class ID
#     print("Class ID: ", class_id)
#     print("Conf: ", conf)
#     # ... Now you can use these values as needed



# from ultralytics import YOLO

# model = YOLO("./src/models/PPEbest.pt")

# results =model("worker.jpeg", task="detect")


# print(results)


# =======================================================================

# LOCAL INFERENCE

import cv2
from ultralytics import YOLO

# Load the YOLO model
model = YOLO("./src/models/PPEbest.engine")

# Run the model on the image
results = model("worker.jpeg", task="detect")

# Retrieve the original image and the bounding boxes
orig_img = results[0].orig_img  # Original image as numpy array
boxes = results[0].boxes.xyxy  # Bounding box coordinates in (x1, y1, x2, y2) format

# Draw bounding boxes on the original image
for box in boxes:
    x1, y1, x2, y2 = map(int, box[:4])  # Coordinates of the bounding box
    cv2.rectangle(orig_img, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Draw rectangle with green color and thickness 2

# Save or display the image with bounding boxes
cv2.imwrite("worker_with_boxes.jpeg", orig_img)


# =======================================================================

# from ultralytics import YOLO

# # Load the Triton Server model
# model = YOLO("http://localhost:8000/PPEbest", task="detect")

# # Run inference on the server
# results = model("worker.jpeg")
# print(results)

# =========================================================================

print("========================================================")


# import cv2
# from ultralytics import YOLO

# # Load the Triton Server model
# # model = YOLO("grpc://localhost:8001/PPEbest", task="detect")
# # model = YOLO("http://localhost:8000/PPEbest", task="detect")

# model = YOLO("http://localhost:8000/PPEtrt", task="detect")
# # model = YOLO("http://localhost:8000/PPEtrt", task="detect")

# # Run inference on the server
# results = model("worker.jpeg")
# print(results)

# # Retrieve the original image and the bounding boxes
# orig_img = results[0].orig_img  # Original image as numpy array
# boxes = results[0].boxes.xyxy  # Bounding box coordinates in (x1, y1, x2, y2) format

# # Draw bounding boxes on the original image
# for box in boxes:
#     x1, y1, x2, y2 = map(int, box[:4])  # Coordinates of the bounding box
#     cv2.rectangle(orig_img, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Draw rectangle with green color and thickness 2

# # Save or display the image with bounding boxes
# cv2.imwrite("worker_with_boxes.jpeg", orig_img)

