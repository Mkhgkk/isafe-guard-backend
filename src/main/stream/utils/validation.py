"""Validation utilities and decorators for stream operations."""

from functools import wraps

from database import get_database
from main.shared import streams
from main.stream.validation import StreamSchema


class ValidationError(Exception):
    """Custom validation error exception."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def require_stream_id(func):
    """Decorator: validates stream_id exists in request data.

    Extracts stream_id from request data and passes it to the decorated function.
    Supports both 'stream_id' and 'streamId' (legacy) parameter names.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        data = self._parse_request_data()
        stream_id = data.get("stream_id") or data.get("streamId")
        if not stream_id:
            return self._create_error_response("Missing stream_id in request data")
        return func(self, stream_id=stream_id, data=data, *args, **kwargs)
    return wrapper


def require_stream_exists(func):
    """Decorator: validates stream exists in database.

    Requires @require_stream_id to be applied first.
    Passes stream_doc to the decorated function.
    """
    @wraps(func)
    def wrapper(self, stream_id=None, *args, **kwargs):
        if not stream_id:
            return self._create_error_response("stream_id parameter is required")

        db = get_database()
        stream_doc = db.streams.find_one({"stream_id": stream_id})
        if not stream_doc:
            return self._create_error_response(
                f"Stream with ID '{stream_id}' not found.", status_code=404
            )
        return func(self, stream_id=stream_id, stream_doc=stream_doc, *args, **kwargs)
    return wrapper


def require_active_stream(func):
    """Decorator: validates stream is currently running.

    Requires @require_stream_id to be applied first.
    Passes video_streaming to the decorated function.
    """
    @wraps(func)
    def wrapper(self, stream_id=None, *args, **kwargs):
        if not stream_id:
            return self._create_error_response("stream_id parameter is required")

        video_streaming = streams.get(stream_id)
        if not video_streaming:
            return self._create_error_response(
                f"Stream '{stream_id}' is not currently active"
            )
        return func(self, stream_id=stream_id, video_streaming=video_streaming,
                    *args, **kwargs)
    return wrapper


def require_ptz_support(func):
    """Decorator: validates stream has PTZ controller.

    Requires @require_active_stream to be applied first.
    """
    @wraps(func)
    def wrapper(self, video_streaming=None, *args, **kwargs):
        if not video_streaming:
            return self._create_error_response("video_streaming parameter is required")

        if not hasattr(video_streaming, 'camera_controller') or not video_streaming.camera_controller:
            return self._create_error_response(
                "PTZ control not available for this stream"
            )
        return func(self, video_streaming=video_streaming, *args, **kwargs)
    return wrapper


class StreamValidator:
    """Utility methods for stream validation."""

    @staticmethod
    def validate_stream_id_only(data: dict) -> str:
        """Validate data containing only stream_id field.

        Args:
            data: Dictionary with stream_id field

        Returns:
            str: The validated stream_id

        Raises:
            ValidationError: If validation fails
        """
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)
        if validation_errors:
            raise ValidationError(f"Validation failed: {validation_errors}")
        return data["stream_id"]

    @staticmethod
    def get_stream_from_db(stream_id: str, projection=None) -> dict:
        """Get stream from database by stream_id.

        Args:
            stream_id: The stream identifier
            projection: Optional MongoDB projection

        Returns:
            dict: The stream document

        Raises:
            ValidationError: If stream not found
        """
        db = get_database()
        stream = db.streams.find_one({"stream_id": stream_id}, projection)
        if not stream:
            raise ValidationError(f"Stream with ID '{stream_id}' not found.", 404)
        return stream

    @staticmethod
    def normalize_stream_id_param(data: dict) -> str:
        """Accept both stream_id and streamId (legacy), return stream_id.

        Args:
            data: Dictionary potentially containing stream_id or streamId

        Returns:
            str: The normalized stream_id, or None if not present
        """
        return data.get("stream_id") or data.get("streamId")
