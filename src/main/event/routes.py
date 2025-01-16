import json
from flask import Blueprint, request
from flask import current_app as app
from main.auth import token_required
from main.event.model import Event
from main import tools

event_blueprint = Blueprint("event", __name__)


@event_blueprint.route("/", methods=["POST"])
def add():
    try:
        data = json.loads(request.data)
        event = Event().create_event(data)
        return tools.JsonResp(event, 200)
    except Exception as e:
        return tools.JsonResp(e, 400)


@event_blueprint.route("/<event_id>", methods=["GET"])
def get_event(event_id):
    return Event().get_event(event_id)


@event_blueprint.route("", methods=["GET"])
def get_events():
    stream_id = request.args.get("stream_id")
    start_timestamp = request.args.get("start_timestamp")
    end_timestamp = request.args.get("end_timestamp")
    limit = int(request.args.get("limit", 20))
    page = int(request.args.get("page", 1))

    return Event().get_events(
        stream_id=stream_id,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        limit=limit,
        page=page,
    )
