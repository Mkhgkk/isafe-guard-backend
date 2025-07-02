import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass
from flask_socketio import join_room, leave_room, send
from flask import request, Request as FlaskRequest
from typing import cast
from main.shared import streams

NAMESPACE = "/default"
logger = logging.getLogger(__name__)


class EventType(Enum):
    """Define all possible event types that can be emitted."""
    SYSTEM_STATUS = "system_status"
    ZOOM_LEVEL = "zoom-level"
    PTZ_AUTOTRACK = "ptz_autotrack"
    
    # Dynamic event types
    ALERT = "alert"
    CUSTOM = "custom"


@dataclass
class SocketEvent:
    """Represents a SocketIO event to be emitted."""
    event_type: EventType
    data: Dict[str, Any]
    room: Optional[str] = None
    namespace: str = NAMESPACE
    broadcast: bool = False
    # New field for dynamic event names
    custom_event_name: Optional[str] = None
    
    @property
    def full_event_name(self) -> str:
        """Get the complete event name, including any dynamic parts."""
        if self.custom_event_name:
            return self.custom_event_name
        return self.event_type.value


class EventBus:
    """Central event bus for managing SocketIO events."""
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable[[SocketEvent], None]]] = {}
    
    def subscribe(self, event_type: EventType, callback: Callable[[SocketEvent], None]):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    
    def publish(self, event: SocketEvent):
        """Publish an event to all subscribers."""
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in event callback: {e}")


class SocketIORequest(FlaskRequest):
    sid: Optional[str]


class SocketIOEmitter:
    """Handles all SocketIO emissions."""
    
    def __init__(self, socketio, event_bus: EventBus):
        self.socketio = socketio
        self.event_bus = event_bus
        self._setup_event_listeners()
    
    def _setup_event_listeners(self):
        """Subscribe to all event types."""
        for event_type in EventType:
            self.event_bus.subscribe(event_type, self._emit_event)
    
    def _emit_event(self, event: SocketEvent):
        """Emit a SocketIO event."""
        try:
            event_name = event.full_event_name
            
            if event.broadcast:
                self.socketio.emit(
                    event_name,
                    event.data,
                    namespace=event.namespace,
                )
            elif event.room:
                self.socketio.emit(
                    event_name,
                    event.data,
                    namespace=event.namespace,
                    room=event.room
                )
            else:
                self.socketio.emit(
                    event_name,
                    event.data,
                    namespace=event.namespace
                )
            
            logger.debug(f"Emitted {event_name} to {event.room or 'all'}")
            
        except Exception as e:
            logger.error(f"Failed to emit event {event_name}: {e}")


class SocketIOHandlers:
    """Handles SocketIO events for video streaming and PTZ camera control."""
    
    def __init__(self, socketio, event_bus: EventBus):
        self.socketio = socketio
        self.event_bus = event_bus
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
    
    def _get_client_id(self) -> Optional[str]:
        """Get the current client's session ID."""
        socketio_request = cast(SocketIORequest, request)
        return socketio_request.sid
    
    def _get_ptz_room_name(self, stream_id: str) -> str:
        """Generate PTZ room name for a stream."""
        return f"ptz-{stream_id}"
    
    def _validate_stream_data(self, data: Dict[str, Any]) -> Optional[str]:
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
    
    def _get_camera_controller(self, stream_id: str):
        """Get camera controller for a stream."""
        stream = streams.get(stream_id)
        if not stream:
            return None
        return stream.camera_controller
    
    def _handle_connect(self):
        """Handle client connection."""
        client_id = self._get_client_id()
        logger.info(f"Client connected: {client_id}")
    
    def _handle_disconnect(self):
        """Handle client disconnection."""
        client_id = self._get_client_id()
        logger.info(f"Client disconnected: {client_id}")
    
    def _handle_join(self, data: Dict[str, Any]):
        """Handle joining a general room."""
        if not isinstance(data, dict) or "room" not in data:
            logger.warning("Invalid join request: missing room")
            return
        
        room = data["room"]
        client_id = self._get_client_id()
        
        join_room(room)
        send(f"{client_id} has entered the room {room}.", room=room)
        logger.info(f"Client {client_id} joined room {room}")
    
    def _handle_leave(self, data: Dict[str, Any]):
        """Handle leaving a general room."""
        if not isinstance(data, dict) or "room" not in data:
            logger.warning("Invalid leave request: missing room")
            return
        
        room = data["room"]
        client_id = self._get_client_id()
        
        leave_room(room)
        send(f"{client_id} has left the room {room}.", room=room)
        logger.info(f"Client {client_id} left room {room}")
    
    def _handle_join_ptz(self, data: Dict[str, Any]):
        """Handle joining a PTZ control room."""
        stream_id = self._validate_stream_data(data)
        if not stream_id:
            return
        
        camera_controller = self._get_camera_controller(stream_id)
        if not camera_controller:
            logger.warning(f"No camera controller for stream {stream_id}")
            return
        
        room = self._get_ptz_room_name(stream_id)
        client_id = self._get_client_id()
        
        join_room(room)
        
        try:
            zoom = camera_controller.get_zoom_level()
            # Use event bus instead of direct emit
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
        stream_id = self._validate_stream_data(data)
        if not stream_id:
            return
        
        room = self._get_ptz_room_name(stream_id)
        client_id = self._get_client_id()
        
        leave_room(room)
        logger.info(f"Client {client_id} left PTZ room {room}")
    
    def _handle_ptz_move(self, data: Dict[str, Any]):
        """Handle PTZ camera movement commands."""
        stream_id = self._validate_stream_data(data)
        if not stream_id:
            return
        
        camera_controller = self._get_camera_controller(stream_id)
        if not camera_controller:
            logger.warning(f"No camera controller for stream {stream_id}")
            return
        
        direction = data.get("direction")
        if not direction:
            logger.warning("Missing direction in PTZ move request")
            return
        
        zoom_amount = data.get("zoom_amount")
        stop = data.get("stop", False)
        room = self._get_ptz_room_name(stream_id)
        
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
        # Use event bus instead of direct emit
        event = SocketEvent(
            event_type=EventType.ZOOM_LEVEL,
            data={"zoom": zoom_amount},
            room=room
        )
        self.event_bus.publish(event)


class SocketIOManager:
    """Singleton manager for SocketIO components."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.event_bus = EventBus()
        self.emitter = None
        self.handlers = None
        self._initialized = True
    
    def initialize(self, socketio):
        """Initialize with socketio instance."""
        if self.emitter is not None or self.handlers is not None:
            logger.warning("SocketIOManager already initialized")
            return
        
        self.emitter = SocketIOEmitter(socketio, self.event_bus)
        self.handlers = SocketIOHandlers(socketio, self.event_bus)
        logger.info("SocketIOManager initialized successfully")
    
    def is_initialized(self) -> bool:
        """Check if manager is initialized."""
        return self.emitter is not None and self.handlers is not None


# Singleton instance
socket_manager = SocketIOManager()


def initialize_socketio(socketio):
    """Initialize SocketIO with the manager."""
    socket_manager.initialize(socketio)


def emit_event(event_type: EventType, data: Dict[str, Any], room: Optional[str] = None, broadcast: bool = False):
    """Convenience function for other modules to emit events."""
    if not socket_manager.is_initialized():
        logger.warning("SocketIOManager not initialized, cannot emit event")
        return
    
    event = SocketEvent(
        event_type=event_type,
        data=data,
        room=room,
        broadcast=broadcast
    )
    socket_manager.event_bus.publish(event)


def emit_dynamic_event(base_event_type: EventType, identifier: str, data: Dict[str, Any], 
                      room: Optional[str] = None, broadcast: bool = False):
    """Emit an event with a dynamic name that includes an identifier."""
    if not socket_manager.is_initialized():
        logger.warning("SocketIOManager not initialized, cannot emit dynamic event")
        return
    
    custom_name = f"{base_event_type.value}-{identifier}"
    event = SocketEvent(
        event_type=base_event_type,
        data=data,
        room=room,
        broadcast=broadcast,
        custom_event_name=custom_name
    )
    socket_manager.event_bus.publish(event)


def emit_custom_event(event_name: str, data: Dict[str, Any], room: Optional[str] = None, broadcast: bool = False):
    """Emit a completely custom event name."""
    if not socket_manager.is_initialized():
        logger.warning("SocketIOManager not initialized, cannot emit custom event")
        return
    
    event = SocketEvent(
        event_type=EventType.CUSTOM,
        data=data,
        room=room,
        broadcast=broadcast,
        custom_event_name=event_name
    )
    socket_manager.event_bus.publish(event)