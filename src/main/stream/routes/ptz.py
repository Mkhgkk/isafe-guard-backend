"""
PTZ control routes
Handles: PTZ autotrack, current position, PTZ controls
"""
from flask import Blueprint
from main.stream.model import Stream

ptz_blueprint = Blueprint('stream_ptz', __name__)


@ptz_blueprint.route("/change_autotrack", methods=["POST"])
def change_autotrack():
    """Toggle PTZ auto tracking for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID for toggling PTZ auto tracking
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream to toggle auto tracking
    responses:
      200:
        description: Auto tracking toggled successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Autotrack changed successfully
            data:
              type: object
              properties:
                ptz_autotrack:
                  type: boolean
                  description: Current auto tracking state
      400:
        description: Invalid stream ID or stream not active or PTZ not supported
        schema:
          type: object
          properties:
            status:
              type: string
              example: error
            message:
              type: string
    """
    return Stream().change_autotrack()


@ptz_blueprint.route("/get_current_ptz_values", methods=["POST"])
def get_current_ptz_values():
    """Get current PTZ (Pan-Tilt-Zoom) values
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream identifier
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: PTZ values retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: ok
            data:
              type: object
              properties:
                x:
                  type: number
                  description: Current pan position
                y:
                  type: number
                  description: Current tilt position
                z:
                  type: number
                  description: Current zoom level
      400:
        description: Invalid input or camera controller not available
      404:
        description: Stream not found or not active
      500:
        description: Unexpected error
    """
    return Stream().get_current_ptz_values()


@ptz_blueprint.route("/ptz_controls", methods=["POST"])
def ptz_controls():
    """Control PTZ camera movements
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: PTZ control command
        required: true
        schema:
          type: object
          required:
            - stream_id
            - command
          properties:
            stream_id:
              type: string
              example: camera_001
            command:
              type: string
              enum: [up, down, left, right, zoom_in, zoom_out, home, stop]
              example: up
            speed:
              type: number
              example: 0.5
              description: Movement speed (0.0 to 1.0)
    responses:
      200:
        description: PTZ command executed successfully
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
        description: Stream not found or PTZ not available
    """
    return Stream().ptz_controls()
