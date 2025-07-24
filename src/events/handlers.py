"""
SocketIO event handlers for video streaming and PTZ camera control.
"""

from typing import Dict, Any, Optional
from flask_socketio import join_room, leave_room, send # pyright: ignore[reportMissingModuleSource]

from .events import EventBus, SocketEvent, EventType, NAMESPACE
from .request_utils import get_client_id
from main.shared import streams
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


class StreamValidator:
    """Validates stream-related data and operations."""
    
    @staticmethod
    def validate_stream_data(data: Dict[str, Any]) -> Optional[str]:
        """Validate and extract stream_id from data."""
        if not isinstance(data, dict):
            log_event(logger, "warning", "Invalid data format received", event_type="validation_error")
            return None
        
        stream_id = data.get("stream_id")
        if not stream_id:
            log_event(logger, "warning", "Missing stream_id in request", event_type="validation_error")
            return None
        
        if stream_id not in streams:
            log_event(logger, "warning", "Stream not found", event_type="validation_error", stream_id=stream_id)
            return None
        
        return stream_id
    
    @staticmethod
    def get_camera_controller(stream_id: str):
        """Get camera controller for a stream."""
        stream = streams.get(stream_id)
        if not stream:
            return None
        return stream.camera_controller
    
    @staticmethod
    def get_ptz_autotrack_status(stream_id: str):
        """Get ptz autotrack status for a stream"""
        stream = streams.get(stream_id)
        if not stream: 
            return None
        return stream.ptz_autotrack


class RoomManager:
    """Manages room operations and naming."""
    
    @staticmethod
    def get_ptz_room_name(stream_id: str) -> str:
        """Generate PTZ room name for a stream."""
        return f"ptz-{stream_id}"


class SocketIOHandlers:
    """Handles SocketIO events for video streaming and PTZ camera control."""
    
    def __init__(self, socketio, event_bus: EventBus):
        self.socketio = socketio
        self.event_bus = event_bus
        self.validator = StreamValidator()
        self.room_manager = RoomManager()
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all SocketIO event handlers."""
        self.socketio.on_event("connect", self._handle_connect, namespace=NAMESPACE)
        self.socketio.on_event("disconnect", self._handle_disconnect, namespace=NAMESPACE)
        self.socketio.on_event("join", self._handle_join, namespace=NAMESPACE)
        self.socketio.on_event("leave", self._handle_leave, namespace=NAMESPACE)
        self.socketio.on_event("join_ptz", self._handle_join_ptz, namespace=NAMESPACE)
        self.socketio.on_event("leave_ptz", self._handle_leave_ptz, namespace=NAMESPACE)
        self.socketio.on_event("ptz_move", self._handle_ptz_move, namespace=NAMESPACE)
    
    def _handle_connect(self):
        """Handle client connection."""
        client_id = get_client_id()
        log_event(logger, "info", f"Client connected: {client_id}", event_type="info")
    
    def _handle_disconnect(self):
        """Handle client disconnection."""
        client_id = get_client_id()
        log_event(logger, "info", f"Client disconnected: {client_id}", event_type="info")
    
    def _handle_join(self, data: Dict[str, Any]):
        """Handle joining a general room."""
        if not isinstance(data, dict) or "room" not in data:
            log_event(logger, "warning", "Invalid join request: missing room", event_type="warning")
            return
        
        room = data["room"]
        client_id = get_client_id()
        
        join_room(room)
        send(f"{client_id} has entered the room {room}.", room=room)
        log_event(logger, "info", f"Client {client_id} joined room {room}", event_type="info")
    
    def _handle_leave(self, data: Dict[str, Any]):
        """Handle leaving a general room."""
        if not isinstance(data, dict) or "room" not in data:
            log_event(logger, "warning", "Invalid leave request: missing room", event_type="warning")
            return
        
        room = data["room"]
        client_id = get_client_id()
        
        leave_room(room)
        send(f"{client_id} has left the room {room}.", room=room)
        log_event(logger, "info", f"Client {client_id} left room {room}", event_type="info")
    
    def _handle_join_ptz(self, data: Dict[str, Any]):
        """Handle joining a PTZ control room."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        ptz_autotrack = self.validator.get_ptz_autotrack_status(stream_id)
        status_event = SocketEvent(event_type=EventType.PTZ_AUTOTRACK, data={"ptz_autotrack": ptz_autotrack})
        self.event_bus.publish(status_event)

        camera_controller = self.validator.get_camera_controller(stream_id)
        if not camera_controller:
            log_event(logger, "warning", f"No camera controller for stream {stream_id}", event_type="warning")
            return
        
        room = self.room_manager.get_ptz_room_name(stream_id)
        client_id = get_client_id()
        
        join_room(room)
        
        try:
            zoom = camera_controller.get_zoom_level()
            event = SocketEvent(
                event_type=EventType.ZOOM_LEVEL,
                data={"zoom": zoom},
                room=room
            )
            self.event_bus.publish(event)
            
            log_event(logger, "info", f"Client {client_id} joined PTZ room {room}", event_type="info")
        except Exception as e:
            log_event(logger, "error", f"Error getting zoom level for stream {stream_id}: {e}", event_type="error")
    
    def _handle_leave_ptz(self, data: Dict[str, Any]):
        """Handle leaving a PTZ control room."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        room = self.room_manager.get_ptz_room_name(stream_id)
        client_id = get_client_id()
        
        leave_room(room)
        log_event(logger, "info", f"Client {client_id} left PTZ room {room}", event_type="info")
    
    def _handle_ptz_move(self, data: Dict[str, Any]):
        """Handle PTZ camera movement commands."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        camera_controller = self.validator.get_camera_controller(stream_id)
        if not camera_controller:
            log_event(logger, "warning", f"No camera controller for stream {stream_id}", event_type="warning")
            return
        
        direction = data.get("direction")
        if not direction:
            log_event(logger, "warning", "Missing direction in PTZ move request", event_type="warning")
            return
        
        zoom_amount = data.get("zoom_amount")
        stop = data.get("stop", False)
        room = self.room_manager.get_ptz_room_name(stream_id)
        
        try:
            # if direction == "zoom_in":
            #     self._handle_zoom_in(camera_controller, zoom_amount, room)
            if stop:
                camera_controller.stop_camera()
                log_event(logger, "info", f"Camera stopped for stream {stream_id}", event_type="info")
            else:
                camera_controller.move_camera(direction)
                log_event(logger, "info", f"Camera moved {direction} for stream {stream_id}", event_type="info")
        except Exception as e:
            log_event(logger, "error", f"Error controlling camera for stream {stream_id}: {e}", event_type="error")
    
    def _handle_zoom_in(self, camera_controller, zoom_amount, room):
        """Handle zoom in operation."""
        if zoom_amount is None:
            log_event(logger, "warning", "Missing zoom_amount for zoom_in operation", event_type="warning")
            return
        
        camera_controller.move_camera("zoom_in", zoom_amount)
        event = SocketEvent(
            event_type=EventType.ZOOM_LEVEL,
            data={"zoom": zoom_amount},
            room=room
        )
        self.event_bus.publish(event)