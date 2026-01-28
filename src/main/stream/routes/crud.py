"""
Stream CRUD routes
Handles: Create, Read (list/single), Update, Delete operations
"""
from flask import Blueprint, request
from main.stream.model import Stream
from main.stream.schemas import (
    STREAM_FULL_SCHEMA,
    STREAM_LIST_ITEM_SCHEMA,
    STREAM_ID_PATH_PARAM,
    STANDARD_SUCCESS_RESPONSE,
    RESPONSES_STANDARD
)

crud_blueprint = Blueprint('stream_crud', __name__)


@crud_blueprint.route("/list", methods=["GET"])
def get_all_streams():
    """Get all streams
    ---
    tags:
      - Stream
    responses:
      200:
        description: List of all streams retrieved successfully
        schema:
          type: array
          items:
            $ref: '#/definitions/StreamListItem'
    definitions:
      StreamListItem:
        type: object
        properties:
          _id:
            type: string
            description: MongoDB ObjectId
          stream_id:
            type: string
            description: Unique stream identifier
          rtsp_link:
            type: string
            description: RTSP URL for the camera stream
          model_name:
            type: string
            description: AI model name used for detection
          location:
            type: string
            description: Physical location of the camera
          description:
            type: string
            description: Camera description
          is_active:
            type: boolean
            description: Whether the stream is currently running
          ptz_autotrack:
            type: boolean
            description: Whether PTZ auto tracking is enabled
          unresolved_events:
            type: integer
            description: Count of unresolved events
          has_unresolved:
            type: boolean
            description: Whether stream has unresolved events
          has_ptz:
            type: boolean
            description: Whether stream has PTZ support
    """
    return Stream().get(None)


@crud_blueprint.route("/<stream_id>", methods=["GET"])
def get_stream_by_id(stream_id):
    """Get a single stream by ID
    ---
    tags:
      - Stream
    parameters:
      - in: path
        name: stream_id
        type: string
        required: true
        description: ID of the stream to retrieve
        example: camera_001
    responses:
      200:
        description: Stream retrieved successfully
        schema:
          $ref: '#/definitions/StreamFull'
      404:
        description: Stream not found
    definitions:
      StreamFull:
        type: object
        properties:
          _id:
            type: string
          stream_id:
            type: string
          rtsp_link:
            type: string
          model_name:
            type: string
          location:
            type: string
          description:
            type: string
          is_active:
            type: boolean
          ptz_autotrack:
            type: boolean
          cam_ip:
            type: string
          ptz_password:
            type: string
          profile_name:
            type: string
          ptz_port:
            type: integer
          ptz_username:
            type: string
          patrol_area:
            type: object
            nullable: true
          patrol_pattern:
            type: object
            nullable: true
          safe_area:
            type: object
            nullable: true
          intrusion_detection:
            type: boolean
          saving_video:
            type: boolean
          patrol_home_position:
            type: object
            nullable: true
          patrol_enabled:
            type: boolean
          patrol_mode:
            type: string
            enum: [pattern, grid, off]
          enable_focus_during_patrol:
            type: boolean
          unresolved_events:
            type: integer
          has_unresolved:
            type: boolean
          focus_enabled:
            type: boolean
          is_hazard_area_configured:
            type: boolean
          has_ptz:
            type: boolean
          is_grid_patrol_configured:
            type: boolean
          is_pattern_patrol_configured:
            type: boolean
    """
    return Stream().get(stream_id)


@crud_blueprint.route("", methods=["GET"])
def get_streams_legacy():
    """Get stream(s) information (DEPRECATED - Use /stream/list or /stream/<stream_id> instead)
    ---
    deprecated: true
    tags:
      - Stream
    parameters:
      - in: query
        name: stream_id
        type: string
        required: false
        description: Optional stream ID to get a specific stream. If not provided, returns all streams.
        example: camera_001
    responses:
      200:
        description: |
          DEPRECATED: This endpoint is kept for backward compatibility only.
          - Use GET /stream/list to get all streams (returns array)
          - Use GET /stream/<stream_id> to get a single stream (returns object)
    """
    stream_id = request.args.get("stream_id")
    return Stream().get(stream_id)


@crud_blueprint.route("", methods=["POST"])
def create_stream():
    """Create a new stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream configuration
        required: true
        schema:
          type: object
          required:
            - stream
          properties:
            stream:
              type: object
              required:
                - stream_id
                - rtsp_link
                - model_name
              properties:
                stream_id:
                  type: string
                  example: camera_001
                rtsp_link:
                  type: string
                  example: rtsp://username:password@192.168.1.100:554/stream
                model_name:
                  type: string
                  example: PPE
                location:
                  type: string
                  example: Building A
                description:
                  type: string
                  example: Main entrance camera
                cam_ip:
                  type: string
                  example: 192.168.1.100
                ptz_port:
                  type: integer
                  example: 8080
                ptz_username:
                  type: string
                  example: admin
                ptz_password:
                  type: string
                  example: password
                profile_name:
                  type: string
            start_stream:
              type: boolean
              example: true
              description: Whether to start the stream immediately after creation
    responses:
      200:
        description: Stream created successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or stream already exists
    """
    return Stream().create_stream()


@crud_blueprint.route("/update_stream", methods=["POST"])
def update_stream():
    """Update stream configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream update data
        required: true
        schema:
          type: object
          required:
            - stream_id
          properties:
            stream_id:
              type: string
              example: camera_001
            name:
              type: string
              example: Updated Camera Name
            location:
              type: string
              example: Building B - Entrance
            rtsp_link:
              type: string
              example: rtsp://username:password@192.168.1.100:554/stream
    responses:
      200:
        description: Stream updated successfully
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
    return Stream().update_stream()


@crud_blueprint.route("/delete_stream", methods=["POST"])
def delete_stream():
    """Delete a stream
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream ID to delete
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
        description: Stream deleted successfully
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
    return Stream().delete_stream()
