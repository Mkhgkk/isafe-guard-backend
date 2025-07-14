"""
SocketIO emitter responsible for handling all event emissions.
Subscribes to the event bus and translates events to SocketIO calls.
"""

from utils.logging_config import get_logger, log_event
from .events import EventBus, SocketEvent, EventType

logger = get_logger(__name__)


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
            
            log_event(logger, "debug", f"Emitted {event_name} to {event.room or 'all'}", event_type="debug")
            
        except Exception as e:
            log_event(logger, "error", f"Failed to emit event {event_name}: {e}", event_type="error")
    
    def cleanup(self):
        """Clean up event listeners."""
        for event_type in EventType:
            self.event_bus.unsubscribe(event_type, self._emit_event)