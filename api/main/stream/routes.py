from flask import current_app as app
from .model import Stream
from main import tools

from flask import Blueprint

stream_blueprint = Blueprint("stream", __name__)

# @app.route('/api/get_all_streams', methods=['GET'])
@stream_blueprint.route("/get_all", methods=["GET"])
def get_all_streams():
    streams = Stream.get_all_streams()
    resp = tools.JsonResp(list(streams), 200)
    return resp