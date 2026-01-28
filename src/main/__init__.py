import os
from flask_cors import CORS
from typing import Optional
from flask import (
    Flask,
    send_from_directory,
)
from pymongo.database import Database
from flask_socketio import SocketIO
from utils.config_loader import config
from flasgger import Swagger

from main.tools import JsonResp
from main.stream.routes import stream_blueprint
from main.user.routes import user_blueprint
from main.event.routes import event_blueprint
from main.system.routes import system_blueprint
from main.logs.routes import logs_blueprint
from main.logs.simple_routes import simple_logs_blueprint
from main.models.routes import models_blueprint

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
    CORS(models_blueprint, resources={r"/*": {"origins": "*"}})

    # Initialize Swagger after CORS
    # Note: basePath is set to /api because nginx proxies to /api/*
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec_1',
                "route": '/apispec_1.json',
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/apidocs/",
        "url_prefix": None  # Don't add prefix to swagger routes
    }

    swagger_template = {
        "swagger": "2.0",
        "basePath": "/api",  # Nginx proxy path - Flask blueprint prefix is added automatically by Swagger
        "info": {
            "title": "iSafe Guard Backend API",
            "description": "API documentation for iSafe Guard surveillance and monitoring system",
            "version": "1.0.0",
            "contact": {
                "name": "iSafe Guard Team",
                "email": "support@isafeguard.com"
            }
        },
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT Authorization header using the Bearer scheme. Example: 'Bearer {token}'"
            }
        },
        "security": [
            {
                "Bearer": []
            }
        ],
        "schemes": ["http", "https"],
        "tags": [
            {
                "name": "User",
                "description": "User authentication and management endpoints"
            },
            {
                "name": "Stream",
                "description": "Video stream management and control endpoints"
            },
            {
                "name": "Event",
                "description": "Event detection and retrieval endpoints"
            },
            {
                "name": "System",
                "description": "System information and health endpoints"
            },
            {
                "name": "Logs",
                "description": "Application logs and monitoring endpoints"
            },
            {
                "name": "Models",
                "description": "AI model management endpoints"
            }
        ]
    }

    Swagger(app, config=swagger_config, template=swagger_template)

    os.environ["TZ"] = config.get("app.timezone", "US/Eastern")

    DB_HOST = config.get("database.uri")
    initialize_database(DB_HOST, config.get("database.name"))
    app.db = get_database()

    app.register_blueprint(stream_blueprint, url_prefix="/stream")
    app.register_blueprint(user_blueprint, url_prefix="/user")
    app.register_blueprint(event_blueprint, url_prefix="/event")
    app.register_blueprint(system_blueprint, url_prefix="/system")
    app.register_blueprint(logs_blueprint, url_prefix="/logs")
    app.register_blueprint(simple_logs_blueprint, url_prefix="/logs")
    app.register_blueprint(models_blueprint, url_prefix="/models")

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
