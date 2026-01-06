"""
Stream control routes
Handles: Start, stop, restart, bulk operations
"""
import json
from flask import Blueprint, request
from main.stream.model import Stream
from main import tools

control_blueprint = Blueprint('stream_control', __name__)


@control_blueprint.route("/start_stream", methods=["POST"])
def start_stream():
    """Start a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID to start
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or stream already running
      404:
        description: Stream not found
    """
    return Stream().start()


@control_blueprint.route("/stop_stream", methods=["POST"])
def stop_stream():
    """Stop a running stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID to stop
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream stopped successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or stream not running
      404:
        description: Stream not found
    """
    return Stream().stop()


@control_blueprint.route("/restart_stream", methods=["POST"])
def restart_stream():
    """Restart a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID to restart
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
    responses:
      200:
        description: Stream restarted successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().restart()


@control_blueprint.route("/bulk_start_streams", methods=["POST"])
def bulk_start_streams():
    """Start multiple streams at once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: List of stream IDs to start
        required: true
        schema:
          type: object
          required:
            - stream_ids
          properties:
            stream_ids:
              type: array
              items:
                type: string
              example: ["camera_001", "camera_002", "camera_003"]
              description: Array of stream IDs to start
    responses:
      200:
        description: Streams started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
            data:
              type: object
              description: Results for each stream
      400:
        description: Missing stream_ids or invalid input
    """
    try:
        data = json.loads(request.data)
        stream_ids = data.get("stream_ids", [])

        if not stream_ids:
            return tools.JsonResp({"message": "stream_ids list is required"}, 400)

        return Stream().bulk_start_streams(stream_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)


@control_blueprint.route("/bulk_stop_streams", methods=["POST"])
def bulk_stop_streams():
    """Stop multiple streams at once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: List of stream IDs to stop
        required: true
        schema:
          type: object
          required:
            - stream_ids
          properties:
            stream_ids:
              type: array
              items:
                type: string
              example: ["camera_001", "camera_002", "camera_003"]
              description: Array of stream IDs to stop
    responses:
      200:
        description: Streams stopped successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
            data:
              type: object
              description: Results for each stream
      400:
        description: Missing stream_ids or invalid input
    """
    try:
        data = json.loads(request.data)
        stream_ids = data.get("stream_ids", [])

        if not stream_ids:
            return tools.JsonResp({"message": "stream_ids list is required"}, 400)

        return Stream().bulk_stop_streams(stream_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)
