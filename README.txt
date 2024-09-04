Project structure

project/
│
├── app.py                      # Main entry point for the application
├── detection/
│   ├── __init__.py             # Initialize the detection module
│   ├── object_detection.py     # Contains ObjectDetection class
├── streaming/
│   ├── __init__.py             # Initialize the streaming module
│   ├── video_streaming.py      # Contains VideoStreaming class
├── routes/
│   ├── __init__.py             # Initialize the routes module
│   ├── api_routes.py           # Contains API route handlers
│   ├── socketio_handlers.py    # Contains Socket.IO event handlers
└── utils/
    ├── __init__.py             # Initialize the utils module
    ├── camera_controller.py    # Contains CameraController class