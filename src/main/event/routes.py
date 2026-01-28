import json
from flask import Blueprint, request
from flask import current_app as app
from main.auth import token_required
from main.event.model import Event
from main import tools

event_blueprint = Blueprint("event", __name__)


@event_blueprint.route("/", methods=["POST"])
def add():
    """Create a new event
    ---
    tags:
      - Event
    parameters:
      - in: body
        name: event
        description: Event data
        required: true
        schema:
          type: object
          properties:
            stream_id:
              type: string
              example: camera_001
            event_type:
              type: string
              example: intrusion_detection
            timestamp:
              type: string
              format: date-time
            metadata:
              type: object
    responses:
      200:
        description: Event created successfully
      400:
        description: Invalid input
    """
    try:
        data = json.loads(request.data)
        event = Event().create_event(data)
        return tools.JsonResp(event, 200)
    except Exception as e:
        return tools.JsonResp(e, 400)


@event_blueprint.route("/<event_id>", methods=["GET"])
def get_event(event_id):
    """Get a specific event by ID
    ---
    tags:
      - Event
    parameters:
      - in: path
        name: event_id
        type: string
        required: true
        description: Event ID to retrieve
    responses:
      200:
        description: Event retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
      404:
        description: Event not found
    """
    return Event().get_event(event_id)


@event_blueprint.route("", methods=["GET"])
def get_events():
    """Get events with filtering and pagination
    ---
    tags:
      - Event
    parameters:
      - in: query
        name: stream_id
        type: string
        required: false
        description: Filter by stream ID
      - in: query
        name: start_timestamp
        type: string
        required: false
        description: Filter events after this timestamp
      - in: query
        name: end_timestamp
        type: string
        required: false
        description: Filter events before this timestamp
      - in: query
        name: is_resolved
        type: boolean
        required: false
        description: Filter by resolution status
      - in: query
        name: limit
        type: integer
        required: false
        default: 20
        description: Number of events per page
      - in: query
        name: page
        type: integer
        required: false
        default: 1
        description: Page number
    responses:
      200:
        description: Events retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: array
              items:
                type: object
            pagination:
              type: object
              properties:
                page:
                  type: integer
                limit:
                  type: integer
                total:
                  type: integer
    """
    stream_id = request.args.get("stream_id")
    start_timestamp = request.args.get("start_timestamp")
    end_timestamp = request.args.get("end_timestamp")
    is_resolved = request.args.get("is_resolved")
    limit = int(request.args.get("limit", 20))
    page = int(request.args.get("page", 1))

    return Event().get_events(
        stream_id=stream_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        is_resolved=is_resolved,
        limit=limit,
        page=page,
    )


@event_blueprint.route("/bulk_resolve", methods=["POST"])
def bulk_resolve():
    """Bulk resolve multiple events
    ---
    tags:
      - Event
    parameters:
      - in: body
        name: event_ids
        description: List of event IDs to resolve
        required: true
        schema:
          type: object
          required:
            - event_ids
          properties:
            event_ids:
              type: array
              items:
                type: string
              example: ["event1", "event2", "event3"]
    responses:
      200:
        description: Events resolved successfully
      400:
        description: Invalid input
    """
    try:
        data = json.loads(request.data)
        event_ids = data.get("event_ids", [])

        if not event_ids:
            return tools.JsonResp({"message": "event_ids list is required"}, 400)

        return Event().bulk_resolve_events(event_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)


@event_blueprint.route("/bulk_delete", methods=["POST"])
def bulk_delete():
    """Bulk delete multiple events
    ---
    tags:
      - Event
    parameters:
      - in: body
        name: event_ids
        description: List of event IDs to delete
        required: true
        schema:
          type: object
          required:
            - event_ids
          properties:
            event_ids:
              type: array
              items:
                type: string
              example: ["event1", "event2", "event3"]
    responses:
      200:
        description: Events deleted successfully
      400:
        description: Invalid input
    """
    try:
        data = json.loads(request.data)
        event_ids = data.get("event_ids", [])

        if not event_ids:
            return tools.JsonResp({"message": "event_ids list is required"}, 400)

        return Event().bulk_delete_events(event_ids)
    except Exception as e:
        return tools.JsonResp({"message": str(e)}, 400)
