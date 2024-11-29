from flask import Blueprint, request
from flask import current_app as app
from main.auth import token_required
from main.event.model import Event
from main import tools 
import json

event_blueprint = Blueprint("event", __name__)

@event_blueprint.route("/", methods=["POST"])
def add():
	try:
		data = json.loads(request.data)
		event = Event().create_event(data)
		return tools.JsonResp(event, 200)
	except Exception as e:
		return tools.JsonResp(e, 400)
	


@event_blueprint.route("/", methods=["GET"])
def get_events():
	event_id = request.args.get('event_id')
	return Event().get(event_id)