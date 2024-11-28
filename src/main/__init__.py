from flask import Flask, request, Blueprint, send_from_directory, send_file, abort, Response
from flask_cors import CORS
from main.tools import JsonResp
from pymongo import MongoClient
# from jose import jwt
import os

# Import Routes
from main.stream.routes import stream_blueprint
from main.user.routes import user_blueprint

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
  app.register_blueprint(user_blueprint, url_prefix="/api/user")

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


  # @app.route('/video/<path:filename>', methods=['GET'])
  # def serve_video(filename):
  #     path = os.path.join(app.static_folder, filename)
  #     if not os.path.exists(path):
  #         abort(404)

  #     def generate():
  #         with open(path, 'rb') as f:
  #             while True:
  #                 chunk = f.read(4096)
  #                 if not chunk:
  #                     break
  #                 yield chunk

  #     # return Response(generate(), mimetype='video/mp4')
  #     return Response(generate(), mimetype='video/x-msvideo')

  # Index Route
  @app.route("/")
  def index():
    return JsonResp({ "status": "Online" }, 200)
  
  
  return app