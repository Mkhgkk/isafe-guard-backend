#!/usr/bin/env python3
"""Simple test script for JSON logging functionality."""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Inline JSON formatter for testing
class JSONFormatter(logging.Formatter):
    def __init__(self, service_name: str = "isafe-guard-backend"):
        super().__init__()
        self.service_name = service_name
    
    def format(self, record: logging.LogRecord) -> str:
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
        
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }
        
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'message', 'asctime'
            }:
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)

def setup_test_logging(enable_json: bool = True):
    """Setup test logging."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    handler = logging.StreamHandler(sys.stdout)
    
    if enable_json:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

def log_event(logger: logging.Logger, level: str, message: str, **kwargs):
    """Log an event with structured context."""
    context = {k: v for k, v in kwargs.items() if v is not None}
    log_method = getattr(logger, level.lower())
    log_method(message, extra=context)

def main():
    """Test JSON logging."""
    print("=== Testing JSON Logging ===")
    setup_test_logging(enable_json=True)
    
    logger = logging.getLogger("test_logger")
    
    # Basic logging
    logger.info("This is a basic info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    # Structured logging
    log_event(
        logger, "info", 
        "Stream started successfully",
        event_type="stream_start",
        stream_id="cam_001",
        camera_id="CAM_001",
        rtsp_url="rtsp://example.com/stream"
    )
    
    log_event(
        logger, "info", 
        "Object detected in stream",
        event_type="detection",
        stream_id="cam_001",
        detection_type="person",
        confidence=0.95,
        bbox=[100, 200, 300, 400]
    )
    
    log_event(
        logger, "error", 
        "Failed to connect to camera",
        event_type="connection_error",
        stream_id="cam_002",
        camera_id="CAM_002",
        error_code="CONN_TIMEOUT",
        retry_count=3
    )
    
    # Exception logging
    try:
        raise ValueError("This is a test exception")
    except Exception:
        logger.exception("Exception occurred during processing")
    
    print("\n=== Testing Plain Text Logging (for comparison) ===")
    setup_test_logging(enable_json=False)
    
    plain_logger = logging.getLogger("plain_logger")
    plain_logger.info("This is plain text logging")
    plain_logger.warning("This is a plain text warning")
    
    log_event(
        plain_logger, "info", 
        "Stream event in plain text",
        event_type="stream_start",
        stream_id="cam_001"
    )

if __name__ == "__main__":
    main()