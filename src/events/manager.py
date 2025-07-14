"""
SocketIO manager that coordinates all components.
Provides singleton access and initialization.
"""

from utils.logging_config import get_logger, log_event
from .events import EventBus
from .emitter import SocketIOEmitter
from .handlers import SocketIOHandlers

logger = get_logger(__name__)


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
            log_event(logger, "warning", "SocketIOManager already initialized", event_type="warning")
            return
        
        self.emitter = SocketIOEmitter(socketio, self.event_bus)
        self.handlers = SocketIOHandlers(socketio, self.event_bus)
        log_event(logger, "info", "SocketIOManager initialized successfully", event_type="info")
    
    def is_initialized(self) -> bool:
        """Check if manager is initialized."""
        return self.emitter is not None and self.handlers is not None
    
    def cleanup(self):
        """Clean up resources."""
        if self.emitter:
            self.emitter.cleanup()
        
        if self.event_bus:
            self.event_bus.clear_subscribers()
        
        self.emitter = None
        self.handlers = None
        log_event(logger, "info", "SocketIOManager cleaned up", event_type="info")
    
    def reset(self):
        """Reset the singleton instance (mainly for testing)."""
        self.cleanup()
        self._initialized = False
        SocketIOManager._instance = None


# Singleton instance
socket_manager = SocketIOManager()