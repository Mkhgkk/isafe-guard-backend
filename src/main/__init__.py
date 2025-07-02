import os
from flask_cors import CORS
from typing import Optional
from flask import (
    Flask,
    send_from_directory,
)
from pymongo.database import Database
from flask_socketio import SocketIO

from main.tools import JsonResp
from main.stream.routes import stream_blueprint
from main.user.routes import user_blueprint
from main.event.routes import event_blueprint
from main.system.routes import system_blueprint

from .extensions import socketio
from events import initialize_socketio
from database import initialize_database, get_database


class IsafeFlask(Flask):
    db: Optional[Database] = None
    socketio: Optional[SocketIO] = None


def create_app():
    app = IsafeFlask(__name__, static_folder="static")
    app.config.from_pyfile("config/config.cfg")

    cors = CORS(app, resources={r"/*": {"origins": "*"}})
    CORS(user_blueprint, resources={r"/*": {"origins": "*"}})
    CORS(stream_blueprint, resources={r"/*": {"origins": "*"}})
    CORS(event_blueprint, resources={r"/*": {"origins": "*"}})

    os.environ["TZ"] = app.config["TIMEZONE"]

    DB_HOST = os.getenv("DB_HOST", app.config["MONGO_URI"])
    initialize_database(DB_HOST, app.config["MONGO_APP_DATABASE"])
    app.db = get_database()

    app.register_blueprint(stream_blueprint, url_prefix="/api/stream")
    app.register_blueprint(user_blueprint, url_prefix="/api/user")
    app.register_blueprint(event_blueprint, url_prefix="/api/event")
    app.register_blueprint(system_blueprint, url_prefix="/api/system")

    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")
    initialize_socketio(socketio)
    # app.socketio = socketio

    @app.route("/static/<path:filename>")
    def serve_static_file(filename):
        assert app.static_folder is not None, "static_folder must be set in Flask app"
        return send_from_directory(app.static_folder, filename)

    @app.route("/video/<path:filename>")
    def serve_video(filename):
        assert app.static_folder is not None, "static_folder must be set in Flask app"
        return send_from_directory(app.static_folder, filename, mimetype="video/mp4")

    @app.route("/")
    def index():
        return JsonResp({"status": "Online"}, 200)

    return app
