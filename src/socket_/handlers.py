"""
SocketIO event handlers for video streaming and PTZ camera control.
"""

import logging
from typing import Dict, Any, Optional
from flask_socketio import join_room, leave_room, send # pyright: ignore[reportMissingModuleSource]

from .events import EventBus, SocketEvent, EventType, NAMESPACE
from .request_utils import get_client_id
from main.shared import streams

logger = logging.getLogger(__name__)


class StreamValidator:
    """Validates stream-related data and operations."""
    
    @staticmethod
    def validate_stream_data(data: Dict[str, Any]) -> Optional[str]:
        """Validate and extract stream_id from data."""
        if not isinstance(data, dict):
            logger.warning("Invalid data format received")
            return None
        
        stream_id = data.get("stream_id")
        if not stream_id:
            logger.warning("Missing stream_id in request")
            return None
        
        if stream_id not in streams:
            logger.warning(f"Stream {stream_id} not found")
            return None
        
        return stream_id
    
    @staticmethod
    def get_camera_controller(stream_id: str):
        """Get camera controller for a stream."""
        stream = streams.get(stream_id)
        if not stream:
            return None
        return stream.camera_controller


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
        logger.info(f"Client connected: {client_id}")
    
    def _handle_disconnect(self):
        """Handle client disconnection."""
        client_id = get_client_id()
        logger.info(f"Client disconnected: {client_id}")
    
    def _handle_join(self, data: Dict[str, Any]):
        """Handle joining a general room."""
        if not isinstance(data, dict) or "room" not in data:
            logger.warning("Invalid join request: missing room")
            return
        
        room = data["room"]
        client_id = get_client_id()
        
        join_room(room)
        send(f"{client_id} has entered the room {room}.", room=room)
        logger.info(f"Client {client_id} joined room {room}")
    
    def _handle_leave(self, data: Dict[str, Any]):
        """Handle leaving a general room."""
        if not isinstance(data, dict) or "room" not in data:
            logger.warning("Invalid leave request: missing room")
            return
        
        room = data["room"]
        client_id = get_client_id()
        
        leave_room(room)
        send(f"{client_id} has left the room {room}.", room=room)
        logger.info(f"Client {client_id} left room {room}")
    
    def _handle_join_ptz(self, data: Dict[str, Any]):
        """Handle joining a PTZ control room."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        camera_controller = self.validator.get_camera_controller(stream_id)
        if not camera_controller:
            logger.warning(f"No camera controller for stream {stream_id}")
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
            
            logger.info(f"Client {client_id} joined PTZ room {room}")
        except Exception as e:
            logger.error(f"Error getting zoom level for stream {stream_id}: {e}")
    
    def _handle_leave_ptz(self, data: Dict[str, Any]):
        """Handle leaving a PTZ control room."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        room = self.room_manager.get_ptz_room_name(stream_id)
        client_id = get_client_id()
        
        leave_room(room)
        logger.info(f"Client {client_id} left PTZ room {room}")
    
    def _handle_ptz_move(self, data: Dict[str, Any]):
        """Handle PTZ camera movement commands."""
        stream_id = self.validator.validate_stream_data(data)
        if not stream_id:
            return
        
        camera_controller = self.validator.get_camera_controller(stream_id)
        if not camera_controller:
            logger.warning(f"No camera controller for stream {stream_id}")
            return
        
        direction = data.get("direction")
        if not direction:
            logger.warning("Missing direction in PTZ move request")
            return
        
        zoom_amount = data.get("zoom_amount")
        stop = data.get("stop", False)
        room = self.room_manager.get_ptz_room_name(stream_id)
        
        try:
            if direction == "zoom_in":
                self._handle_zoom_in(camera_controller, zoom_amount, room)
            elif stop:
                camera_controller.stop_camera()
                logger.info(f"Camera stopped for stream {stream_id}")
            else:
                camera_controller.move_camera(direction)
                logger.info(f"Camera moved {direction} for stream {stream_id}")
        except Exception as e:
            logger.error(f"Error controlling camera for stream {stream_id}: {e}")
    
    def _handle_zoom_in(self, camera_controller, zoom_amount, room):
        """Handle zoom in operation."""
        if zoom_amount is None:
            logger.warning("Missing zoom_amount for zoom_in operation")
            return
        
        camera_controller.move_camera("zoom_in", zoom_amount)
        event = SocketEvent(
            event_type=EventType.ZOOM_LEVEL,
            data={"zoom": zoom_amount},
            room=room
        )
        self.event_bus.publish(event)