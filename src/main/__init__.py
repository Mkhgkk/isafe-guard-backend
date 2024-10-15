from flask import Flask, request, Blueprint, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from main.tools import JsonResp
# from jose import jwt
import os

# Import Routes
from main.stream.routes import stream_blueprint

from socket_.socketio_instance import socketio
from socket_.socketio_handlers import setup_socketio_handlers

def create_app():

  # Flask Config
  # app = Flask(__name__)
  app = Flask(__name__, static_folder='static')
  app.config.from_pyfile("config/config.cfg")
#   cors = CORS(app, resources={r"/*": { "origins": app.config["FRONTEND_DOMAIN"] }})
  cors = CORS(app, resources={r"/*": { "origins": "*" }})

  # Misc Config
  os.environ["TZ"] = app.config["TIMEZONE"]

  # Database Config
  if app.config["ENVIRONMENT"] == "development":
    # mongo = MongoClient(app.config["MONGO_HOSTNAME"], app.config["MONGO_PORT"])
    # app.db = mongo[app.config["MONGO_APP_DATABASE"]]
    mongo = MongoClient(app.config["MONGO_URI"])
    app.db = mongo[app.config["MONGO_APP_DATABASE"]]
  else:
    mongo = MongoClient("localhost")
    mongo[app.config["MONGO_AUTH_DATABASE"]].authenticate(app.config["MONGO_AUTH_USERNAME"], app.config["MONGO_AUTH_PASSWORD"])
    app.db = mongo[app.config["MONGO_APP_DATABASE"]]

  

  # Register Blueprints
  app.register_blueprint(stream_blueprint, url_prefix="/api/stream")

  # Socket initialization
  socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
  setup_socketio_handlers(socketio)
  app.socketio = socketio

  @app.route('/static/<path:filename>')
  def serve_static_file(filename):
      return send_from_directory(app.static_folder, filename)

  # Index Route
  @app.route("/")
  def index():
    return JsonResp({ "status": "Online" }, 200)
  
  
  return app