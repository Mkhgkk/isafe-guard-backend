class StreamingError(Exception):
    """Base exception for streaming errors."""
    pass

class PipelineError(StreamingError):
    """Pipeline-related errors."""
    pass

class ConnectionError(StreamingError):
    """Connection-related errors."""
    pass