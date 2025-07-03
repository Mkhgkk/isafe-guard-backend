"""
Event system core components.
Handles event definitions, event bus, and event data structures.
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)

NAMESPACE = "/default"


class EventType(Enum):
    """Define all possible event types that can be emitted."""
    SYSTEM_STATUS = "system_status"
    ZOOM_LEVEL = "zoom-level"
    PTZ_AUTOTRACK = "ptz-autotrack"
    # PTZ_AUTOTRACK_STATUS = "ptz_autotrack_status"
    
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
    
    def unsubscribe(self, event_type: EventType, callback: Callable[[SocketEvent], None]):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                logger.warning(f"Callback not found for event type {event_type}")
    
    def clear_subscribers(self, event_type: Optional[EventType] = None):
        """Clear subscribers for a specific event type or all event types."""
        if event_type:
            self._subscribers[event_type] = []
        else:
            self._subscribers.clear()
    
    def get_subscriber_count(self, event_type: EventType) -> int:
        """Get the number of subscribers for an event type."""
        return len(self._subscribers.get(event_type, []))