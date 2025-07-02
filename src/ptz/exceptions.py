class CameraSystemError(Exception):
    """Base exception for camera system errors."""
    pass


class CameraConnectionError(CameraSystemError):
    """Raised when camera connection fails."""
    pass


class CameraOperationError(CameraSystemError):
    """Raised when camera operation fails."""
    pass