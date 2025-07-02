"""
SocketIO Event System Package

A modular, event-driven SocketIO system with the following components:

- events: Core event definitions and event bus
- emitter: Handles SocketIO emissions  
- handlers: SocketIO event handlers
- manager: Coordinates all components
- api: Public interface for other modules

Usage:
    from socketio_system import initialize_socketio, emit_event, EventType
    
    # Initialize
    initialize_socketio(socketio)
    
    # Emit events
    emit_event(EventType.SYSTEM_STATUS, {"cpu": 50, "gpu": 30}, broadcast=True)
"""

from .api import (
    initialize_socketio,
    emit_event,
    emit_dynamic_event, 
    emit_custom_event,
    is_initialized,
    cleanup,
    reset,
    EventType,
    SocketEvent
)


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