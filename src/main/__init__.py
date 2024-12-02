import os
from flask_cors import CORS
from flask import Flask, request, Blueprint, send_from_directory, send_file, abort, Response
from pymongo import MongoClient

from main.tools import JsonResp
from main.stream.routes import stream_blueprint
from main.user.routes import user_blueprint
from main.event.routes import event_blueprint

from socket_.socketio_instance import socketio
from socket_.socketio_handlers import setup_socketio_handlers

from database import MongoDatabase, initialize_database, get_database


def create_app():
  app = Flask(__name__, static_folder='static')
  app.config.from_pyfile("config/config.cfg")
  # cors = CORS(app, resources={r"/*": { "origins": app.config["FRONTEND_DOMAIN"] }})
  # cors = CORS(app, resources={r"/*": { "origins": "*" }})

  cors = CORS(app, resources={r"/*": { "origins": "*" }})
  CORS(user_blueprint, resources={r"/*": {"origins": "*"}})
  CORS(stream_blueprint, resources={r"/*": {"origins": "*"}})
  CORS(event_blueprint, resources={r"/*": {"origins": "*"}})


  # Misc Config
  os.environ["TZ"] = app.config["TIMEZONE"]

  # Database Config
  if app.config["ENVIRONMENT"] == "development":
    # mongo = MongoClient(app.config["MONGO_HOSTNAME"], app.config["MONGO_PORT"])
    # app.db = mongo[app.config["MONGO_APP_DATABASE"]]

    # mongo = MongoClient(app.config["MONGO_URI"])
    # app.db = mongo[app.config["MONGO_APP_DATABASE"]]

    initialize_database(app.config["MONGO_URI"], app.config["MONGO_APP_DATABASE"])
    app.db = get_database()
  else:
    mongo = MongoClient("localhost")
    mongo[app.config["MONGO_AUTH_DATABASE"]].authenticate(app.config["MONGO_AUTH_USERNAME"], app.config["MONGO_AUTH_PASSWORD"])
    app.db = mongo[app.config["MONGO_APP_DATABASE"]]

  # Register Blueprints
  app.register_blueprint(stream_blueprint, url_prefix="/api/stream")
  app.register_blueprint(user_blueprint, url_prefix="/api/user")
  app.register_blueprint(event_blueprint, url_prefix="/api/event")

  # Socket initialization
  socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
  setup_socketio_handlers(socketio)
  app.socketio = socketio

  @app.route('/static/<path:filename>')
  def serve_static_file(filename):
      return send_from_directory(app.static_folder, filename)
  
  @app.route('/video/<path:filename>')
  def serve_video(filename):
      return send_from_directory(app.static_folder, filename, mimetype='video/mp4')

  # Index Route
  @app.route("/")
  def index():
    return JsonResp({ "status": "Online" }, 200)
  
  
  return app