import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def __init__(self, service_name: str = "isafe-guard-backend"):
        super().__init__()
        self.service_name = service_name
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": self.service_name,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "process": record.process,
        }
        
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }
        
        # Add custom fields from extra
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'message', 'asctime'
            }:
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    service_name: str = "isafe-guard-backend",
    enable_json: bool = True
) -> None:
    """Configure application logging with JSON format."""
    
    # Remove existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    
    if enable_json:
        formatter = JSONFormatter(service_name)
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    handler.setFormatter(formatter)
    
    # Set level
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler.setLevel(log_level)
    root_logger.setLevel(log_level)
    
    # Add handler to root logger
    root_logger.addHandler(handler)
    
    # Set specific logger levels
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: str,
    message: str,
    event_type: Optional[str] = None,
    stream_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    detection_type: Optional[str] = None,
    confidence: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None
) -> None:
    """Log an event with structured context."""
    context = {
        "event_type": event_type,
        "stream_id": stream_id,
        "camera_id": camera_id,
        "detection_type": detection_type,
        "confidence": confidence,
    }
    
    if extra:
        context.update(extra)
    
    # Remove None values
    context = {k: v for k, v in context.items() if v is not None}
    
    log_method = getattr(logger, level.lower())
    log_method(message, extra=context)


# Database logging integration
_database_handler_initialized = False

def setup_database_logging_integration():
    """Setup database logging after Flask app is ready."""
    global _database_handler_initialized
    
    if _database_handler_initialized:
        return
    
    try:
        from utils.database_log_handler import DatabaseLogHandler
        
        # Create and add database handler
        db_handler = DatabaseLogHandler()
        
        # Add to root logger (this captures all log events)
        root_logger = logging.getLogger()
        root_logger.addHandler(db_handler)
        
        _database_handler_initialized = True
        print(f"✅ Database logging integration initialized successfully")
        
    except Exception as e:
        print(f"❌ Failed to setup database logging integration: {e}")


def get_database_logging_status():
    """Get the status of database logging."""
    return _database_handler_initialized