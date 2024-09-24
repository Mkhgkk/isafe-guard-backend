from flask_socketio import SocketIO, emit, join_room, leave_room, send
# from utils.camera_controller import CameraController
# from streaming.video_streaming import VideoStreaming
from flask import request
# from routes.api_routes import app

# socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')

from main.shared import streams
from main.shared import camera_controllers


# streams = {}
# camera_controllers = {}

def setup_socketio_handlers(socketio):
    @socketio.on('connect', namespace='/video')
    def video_connect():
        print('Client connected')

    @socketio.on('disconnect', namespace='/video')
    def video_disconnect():
        print('Client disconnected')

    @socketio.on('join', namespace='/video')
    def handle_join(data):
        room = data['room']
        join_room(room)
        send(f"{request.sid} has entered the room {room}.", room=room)

    @socketio.on('leave', namespace='/video')
    def handle_leave(data):
        room = data['room']
        leave_room(room)
        send(f"{request.sid} has left the room {room}.", room=room)

    @socketio.on('join_ptz', namespace='/video')
    def join_ptz_room(data):
        stream_id = data["stream_id"]
        camera_controller = camera_controllers[stream_id]

        room = f"ptz-{stream_id}"
        join_room(room)

        zoom = camera_controller.get_zoom_level()
        socketio.emit(f'zoom-level', {'zoom': zoom}, namespace='/video', room=room)

    @socketio.on('leave_ptz', namespace='/video')
    def leave_ptz_room(data):
        stream_id = data["stream_id"]
        room = f"ptz-{stream_id}"

        leave_room(room)

    @socketio.on('ptz_move', namespace='/video')
    def ptz_change_zoom(data):
        stream_id = data["stream_id"]
        zoom_amount = data.get("zoom_amount", None)
        direction = data["direction"]
        stop = data.get("stop", False)
        camera_controller = camera_controllers[stream_id]
        room = f"ptz-{stream_id}"

        if direction == 'zoom_in':
            camera_controller.move_camera(direction, zoom_amount)
            socketio.emit(f'zoom-level', {'zoom': zoom_amount}, namespace='/video', room=room)
        elif stop is False:  
            camera_controller.move_camera(direction)
        elif stop is True: 
            camera_controller.stop_camera()

