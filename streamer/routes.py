from flask import current_app as app
from .model import Streams
import tools

@app.route('/api/get_all_streams', methods=['GET'])
def get_all_streams():
    streams = Streams.get_all_streams()
    resp = tools.JsonResp(list(streams), 200)
    return resp