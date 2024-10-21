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


import numpy as np
import tritonclient.grpc as grpcclient
from PIL import Image

# Load and preprocess the image
image_path = "worker.jpeg"
image = Image.open(image_path).resize((640, 640))
image = np.array(image).astype(np.float32)
image = np.transpose(image, (2, 0, 1))  # Convert to CHW format
image = np.expand_dims(image, axis=0)  # Add batch dimension

# Create Triton gRPC client
url = "localhost:8001"  # gRPC typically uses port 8001
model_name = "PPEbest"
client = grpcclient.InferenceServerClient(url=url)

# Prepare inputs and outputs
inputs = [grpcclient.InferInput("images", image.shape, "FP32")]
inputs[0].set_data_from_numpy(image)

outputs = [grpcclient.InferRequestedOutput("output0")]

# Perform inference
response = client.infer(model_name, inputs, outputs=outputs)

# Get the output
output_data = response.as_numpy("output0")
print("Inference result:", output_data)