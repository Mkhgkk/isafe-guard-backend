"""
Public API for the SocketIO event system.
This is the main interface other modules should use.
"""

import logging
from typing import Dict, Any, Optional

from .events import SocketEvent, EventType
from .manager import socket_manager

logger = logging.getLogger(__name__)


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


def is_initialized() -> bool:
    """Check if the SocketIO system is initialized."""
    return socket_manager.is_initialized()


def cleanup():
    """Clean up the SocketIO system."""
    socket_manager.cleanup()


def reset():
    """Reset the SocketIO system (mainly for testing)."""
    socket_manager.reset()


# Re-export commonly used types and enums for convenience
__all__ = [
    'initialize_socketio',
    'emit_event', 
    'emit_dynamic_event',
    'emit_custom_event',
    'is_initialized',
    'cleanup',
    'reset',
    'EventType',
    'SocketEvent'
]