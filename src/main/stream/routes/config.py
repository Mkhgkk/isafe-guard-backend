"""
Stream configuration routes
Handles: Danger zone, safe area, camera mode, intrusion detection, video saving, alerts, frames
"""
from flask import Blueprint, request
from main.stream.model import Stream
from main import tools
from events import emit_dynamic_event, EventType

config_blueprint = Blueprint('stream_config', __name__)


@config_blueprint.route("/set_danger_zone", methods=["POST"])
def set_danger_zone():
    """Configure safe/danger zone for intrusion detection
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Danger zone configuration
        required: true
        schema:
          type: object
          required:
            - streamId
            - coords
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
            coords:
              type: array
              items:
                type: array
                items:
                  type: number
              example: [[100, 100], [400, 100], [400, 300], [100, 300]]
              description: Array of coordinate pairs defining the danger zone polygon
            image:
              type: string
              example: /static/frame_refs/frame_12345_camera_001.jpg
              description: Path to reference image
            static:
              type: boolean
              example: true
              description: Whether the camera is stationary (true) or can move (false)
    responses:
      200:
        description: Danger zone updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Danger zone updated successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                message:
                  type: string
      400:
        description: Missing required fields or invalid data
      404:
        description: Stream not found
    """
    return Stream().set_danger_zone()


@config_blueprint.route("/set_camera_mode", methods=["POST"])
def set_camera_mode():
    """Set camera mode for hazard area tracking
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Camera mode configuration
        required: true
        schema:
          type: object
          required:
            - streamId
            - static
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
            static:
              type: boolean
              example: true
              description: Camera mode - true for static (stationary), false for dynamic (moving)
    responses:
      200:
        description: Camera mode updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Camera mode updated successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                message:
                  type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().set_camera_mode()


@config_blueprint.route("/get_camera_mode", methods=["POST"])
def get_camera_mode():
    """Get current camera mode for hazard area tracking
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
            - streamId
          properties:
            streamId:
              type: string
              example: camera_001
              description: ID of the stream
    responses:
      200:
        description: Camera mode retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: Success
            message:
              type: string
              example: Camera mode retrieved successfully
            data:
              type: object
              properties:
                static_mode:
                  type: boolean
                  description: Current camera mode - true for static, false for dynamic
                message:
                  type: string
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().get_camera_mode()


@config_blueprint.route("/get_safe_area", methods=["POST"])
def get_safe_area():
    """Get saved safe area configuration
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
        description: Safe area configuration retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                coords:
                  type: array
                  items:
                    type: array
                    items:
                      type: number
                  description: Coordinate pairs defining the safe area polygon
                static_mode:
                  type: boolean
                  description: Camera mode setting
                reference_image:
                  type: string
                  description: Path to reference image
      400:
        description: Invalid input
      404:
        description: Stream or safe area not found
    """
    return Stream().get_safe_area()


@config_blueprint.route("/toggle_intrusion_detection", methods=["POST"])
def toggle_intrusion_detection():
    """Toggle intrusion detection for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID for toggling intrusion detection
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
        description: Intrusion detection toggled successfully
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
              properties:
                intrusion_detection:
                  type: boolean
                  description: Current intrusion detection state
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().toggle_intrusion_detection()


@config_blueprint.route("/toggle_saving_video", methods=["POST"])
def toggle_saving_video():
    """Toggle video saving for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID for toggling video saving
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
        description: Video saving toggled successfully
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
              properties:
                saving_video:
                  type: boolean
                  description: Current video saving state
      400:
        description: Invalid input
      404:
        description: Stream not found
    """
    return Stream().toggle_saving_video()


@config_blueprint.route("/alert", methods=["GET"])
def alert():
    """Trigger an alert event for a stream
    ---
    tags:
      - Stream
    parameters:
      - in: query
        name: stream_id
        type: string
        required: true
        description: ID of the stream to trigger alert for
        example: camera_001
    responses:
      200:
        description: Alert event triggered successfully
        schema:
          type: object
          properties:
            data:
              type: string
              example: ok
    """

    stream_id = request.args.get("stream_id")

    room = stream_id
    data = {"type": "intrusion"}

    emit_dynamic_event(
        base_event_type=EventType.ALERT, identifier=stream_id, data=data, room=room
    )

    return tools.JsonResp({"data": "ok"}, 200)


@config_blueprint.route("/get_current_frame", methods=["POST"])
def get_current_frame():
    """Get current frame from an active stream
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
        description: Current frame captured successfully
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
              type: string
              example: frame_1234567890_camera_001.jpg
              description: Filename of the captured frame
      400:
        description: Invalid input or error capturing frame
      404:
        description: Stream not active
    """
    return Stream().get_current_frame()
