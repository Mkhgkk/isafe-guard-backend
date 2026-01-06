"""
Patrol routes
Handles: Toggle patrol, patrol area, patrol pattern, preview
"""
from flask import Blueprint
from main.stream.model import Stream

patrol_blueprint = Blueprint('stream_patrol', __name__)


@patrol_blueprint.route("/toggle_patrol", methods=["POST"])
def toggle_patrol():
    """Toggle patrol mode for PTZ camera
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - patrol_mode
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            patrol_mode:
              type: string
              enum: [pattern, grid, off]
              example: grid
              description: Patrol mode - 'pattern' for custom waypoints, 'grid' for automatic grid patrol, 'off' to disable
    responses:
      200:
        description: Patrol mode updated successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or stream not found
      404:
        description: Stream not found
    """
    return Stream().toggle_patrol()


@patrol_blueprint.route("/toggle_patrol_focus", methods=["POST"])
def toggle_patrol_focus():
    """Toggle focus during patrol feature
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Stream configuration for patrol focus
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
            enable_focus_during_patrol:
              type: boolean
              example: true
              description: Whether to enable auto-focus during patrol
    responses:
      200:
        description: Patrol focus setting updated successfully
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
    return Stream().toggle_patrol_focus()


@patrol_blueprint.route("/save_patrol_area", methods=["POST"])
def save_patrol_area():
    """Save patrol area configuration
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol area configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - patrol_area
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            patrol_area:
              type: object
              description: Patrol area configuration data
              properties:
                coordinates:
                  type: array
                  items:
                    type: array
                    items:
                      type: number
                  description: Coordinates defining the patrol area
    responses:
      200:
        description: Patrol area saved successfully
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
    return Stream().save_patrol_area()


@patrol_blueprint.route("/get_patrol_area", methods=["POST"])
def get_patrol_area():
    """Get saved patrol area configuration
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
        description: Patrol area retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              description: Patrol area configuration
      400:
        description: Invalid input
      404:
        description: Stream or patrol area not found
    """
    return Stream().get_patrol_area()


@patrol_blueprint.route("/save_patrol_pattern", methods=["POST"])
def save_patrol_pattern():
    """Save custom patrol pattern with waypoints
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol pattern configuration
        required: true
        schema:
          type: object
          required:
            - stream_id
            - coordinates
          properties:
            stream_id:
              type: string
              example: camera_001
              description: ID of the stream
            coordinates:
              type: array
              items:
                type: object
                properties:
                  pan:
                    type: number
                    description: Pan position
                  tilt:
                    type: number
                    description: Tilt position
                  zoom:
                    type: number
                    description: Zoom level
              example: [{"pan": 0.1, "tilt": 0.2, "zoom": 1.0}, {"pan": 0.5, "tilt": 0.3, "zoom": 1.5}]
              description: Array of PTZ waypoints for the patrol pattern
    responses:
      200:
        description: Patrol pattern saved successfully
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
    return Stream().save_patrol_pattern()


@patrol_blueprint.route("/preview_patrol_pattern", methods=["POST"])
def preview_patrol_pattern():
    """Preview custom patrol pattern by executing once
    ---
    tags:
      - Stream
    parameters:
      - in: body
        name: body
        description: Patrol pattern preview request
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
            coordinates:
              type: array
              items:
                type: object
                properties:
                  pan:
                    type: number
                  tilt:
                    type: number
                  zoom:
                    type: number
              description: Optional waypoints to preview. If not provided, uses saved pattern.
    responses:
      200:
        description: Patrol pattern preview started successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            message:
              type: string
      400:
        description: Invalid input or no pattern available
      404:
        description: Stream not found or not active
    """
    return Stream().preview_patrol_pattern()


@patrol_blueprint.route("/get_patrol_pattern", methods=["POST"])
def get_patrol_pattern():
    """Get saved patrol pattern from database
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
        description: Patrol pattern retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                coordinates:
                  type: array
                  items:
                    type: object
                    properties:
                      pan:
                        type: number
                      tilt:
                        type: number
                      zoom:
                        type: number
                  description: Array of PTZ waypoints
      400:
        description: Invalid input
      404:
        description: Stream or patrol pattern not found
    """
    return Stream().get_patrol_pattern()
