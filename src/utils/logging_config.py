import json
import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional


# ANSI color codes for different log levels
class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright foreground colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'


# Color mapping for log levels
LOG_COLORS = {
    'DEBUG': Colors.BRIGHT_BLACK,
    'INFO': Colors.BRIGHT_CYAN,
    'WARNING': Colors.BRIGHT_YELLOW,
    'ERROR': Colors.BRIGHT_RED,
    'CRITICAL': Colors.BOLD + Colors.BRIGHT_RED,
}


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


class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output."""
    
    def __init__(self, service_name: str = "isafe-guard-backend", use_colors: bool = True):
        super().__init__()
        self.service_name = service_name
        self.use_colors = use_colors and self._supports_color()
        
        # Base format without colors
        self.base_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    def _supports_color(self) -> bool:
        """Check if the terminal supports ANSI colors."""
        # Check for NO_COLOR environment variable (disable colors)
        if os.environ.get('NO_COLOR'):
            return False
            
        # Check for FORCE_COLOR environment variable (force enable colors)
        if os.environ.get('FORCE_COLOR') or os.environ.get('COLORTERM'):
            return True
        
        # For Docker environments, enable colors if TERM suggests support
        term = os.environ.get('TERM', '').lower()
        if any(term.startswith(t) for t in ['xterm', 'color', 'ansi', 'cygwin', 'linux', 'screen']):
            return True
        
        # Enable colors for common CI/CD and containerized environments
        if any(env in os.environ for env in ['CI', 'DOCKER_CONTAINER', 'KUBERNETES_SERVICE_HOST']):
            return True
        
        # Check if output is a TTY (traditional check)
        if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
            return True
            
        return False
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors if supported."""
        if not self.use_colors:
            # Use simple format without colors
            formatter = logging.Formatter(self.base_format)
            return formatter.format(record)
        
        # Get color for log level
        level_color = LOG_COLORS.get(record.levelname, Colors.WHITE)
        
        # Format the message components
        timestamp = self.formatTime(record)
        logger_name = record.name
        level_name = record.levelname
        message = record.getMessage()
        
        # Apply colors to different components
        colored_timestamp = f"{Colors.BRIGHT_BLACK}{timestamp}{Colors.RESET}"
        colored_logger = f"{Colors.BLUE}{logger_name}{Colors.RESET}"
        colored_level = f"{level_color}{level_name}{Colors.RESET}"
        colored_message = f"{level_color}{message}{Colors.RESET}"
        
        # Combine into final format
        return f"{colored_timestamp} - {colored_logger} - {colored_level} - {colored_message}"


def setup_logging(
    level: str = "INFO",
    service_name: str = "isafe-guard-backend",
    enable_json: bool = True,
    enable_file_logging: bool = True,
    enable_colors: bool = None,  # None means auto-detect
    log_dir: str = "/tmp/isafe-guard-logs"
) -> None:
    """Configure application logging with colored console output and JSON file logging.
    
    Args:
        enable_colors: None (auto-detect), True (force enable), False (force disable)
    """
    
    # Remove existing handlers and properly close them to prevent file descriptor leaks
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()  # Close handler to release file descriptors
        root_logger.removeHandler(handler)
    
    # Determine if colors should be used
    if enable_colors is None:
        # Auto-detect color support
        use_colors = True  # Default to True for better Docker experience
    else:
        use_colors = enable_colors
    
    # Create formatter for console
    if use_colors:
        console_formatter = ColoredFormatter(service_name, use_colors=True)
    elif enable_json:
        console_formatter = JSONFormatter(service_name)
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    # Create console handler with colored formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    
    # Set level
    log_level = getattr(logging, level.upper(), logging.INFO)
    console_handler.setLevel(log_level)
    root_logger.setLevel(log_level)
    
    # Add console handler
    root_logger.addHandler(console_handler)
    
    # Add file handler for Promtail integration
    if enable_file_logging:
        try:
            # Create log directory structure
            backend_log_dir = os.path.join(log_dir, "backend")
            os.makedirs(backend_log_dir, exist_ok=True)
            
            # Create JSON formatter for file logging (always use JSON for files)
            json_formatter = JSONFormatter(service_name)
            
            # Create rotating file handler for backend logs
            log_file_path = os.path.join(backend_log_dir, f"{service_name}.log")
            file_handler = RotatingFileHandler(
                log_file_path,
                maxBytes=50 * 1024 * 1024,  # 50MB per file
                backupCount=10  # Keep 10 backup files
            )
            file_handler.setFormatter(json_formatter)
            file_handler.setLevel(log_level)
            root_logger.addHandler(file_handler)
            
            print(f"✅ File logging enabled: {log_file_path}")
            
        except Exception as e:
            print(f"❌ Failed to setup file logging: {e}")
            print("   Continuing with console logging only")
    
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


def test_colored_logging():
    """Test function to demonstrate colored logging output."""
    setup_logging(level="DEBUG", enable_colors=True)
    logger = get_logger("test.colored.logging")
    
    print("Testing colored logging output:")
    logger.debug("This is a DEBUG message - should be gray")
    logger.info("This is an INFO message - should be cyan")  
    logger.warning("This is a WARNING message - should be yellow")
    logger.error("This is an ERROR message - should be red")
    logger.critical("This is a CRITICAL message - should be bold red")
    
    # Test with structured logging
    log_event(
        logger, 
        "info", 
        "This is a structured log message", 
        event_type="test",
        extra={"test_data": "colored logging"}
    )


if __name__ == "__main__":
    # Run test when file is executed directly
    test_colored_logging()