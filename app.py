from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from routes.socketio_handlers import setup_socketio_handlers
from socketio_instance import socketio
from routes.api_routes import app


CORS(app)
# cors = CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
# socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

setup_socketio_handlers(socketio)

app.socketio = socketio


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)




