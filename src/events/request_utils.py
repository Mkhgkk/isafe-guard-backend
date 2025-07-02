"""
Request utilities and types for SocketIO handlers.
"""

from typing import Optional
from flask import request, Request as FlaskRequest # pyright: ignore[reportMissingImports]
from typing import cast


class SocketIORequest(FlaskRequest):
    """Extended Flask request with SocketIO session ID."""
    sid: Optional[str]


def get_client_id() -> Optional[str]:
    """Get the current client's session ID."""
    socketio_request = cast(SocketIORequest, request)
    return socketio_request.sid