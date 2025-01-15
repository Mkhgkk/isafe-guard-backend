from flask import Blueprint
from flask import current_app as app
from main.auth import token_required
from main.system.models import System

system_blueprint = Blueprint("system", __name__)

@system_blueprint.route("", methods=["GET"])
def get():
	return System().get()

@system_blueprint.route("/disk", methods=["GET"])
def get_disk():
	return System().get_disk()

@system_blueprint.route("/retention", methods=["GET"])
def get_retention():
	return System().get_retention()

@system_blueprint.route("/retention", methods=["POST"])
def update_retention():
	return System().update_retention()

@system_blueprint.route("/watch_notif", methods=["POST"])
def update_watch_notif():
	return System().update_watch_notif()

@system_blueprint.route("/email_notif", methods=["POST"])
def update_email_notif():
	return System().update_email_notif()