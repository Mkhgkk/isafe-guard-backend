from flask import Blueprint
from flask import current_app as app
from main.auth import token_required
from main.system.models import System

system_blueprint = Blueprint("system", __name__)

@system_blueprint.route("/disk", methods=["GET"])
def get_disk():
	return System().get_disk()
