#!/usr/bin/env python3
"""Test script for JSON logging functionality."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logging_config import setup_logging, get_logger, log_event

def test_json_logging():
    """Test various logging scenarios."""
    print("Setting up JSON logging...")
    setup_logging(level="INFO", enable_json=True)
    
    # Test basic logger
    logger = get_logger("test_logger")
    
    print("\n=== Testing Basic Logging ===")
    logger.info("This is a basic info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.debug("This debug message should not appear (level is INFO)")
    
    print("\n=== Testing Structured Event Logging ===")
    
    # Test stream events
    log_event(
        logger, "info", 
        "Stream started successfully",
        event_type="stream_start",
        stream_id="cam_001",
        camera_id="CAM_001",
        extra={"rtsp_url": "rtsp://example.com/stream"}
    )
    
    # Test detection events
    log_event(
        logger, "info", 
        "Object detected in stream",
        event_type="detection",
        stream_id="cam_001",
        detection_type="person",
        confidence=0.95,
        extra={"bbox": [100, 200, 300, 400]}
    )
    
    # Test error events
    log_event(
        logger, "error", 
        "Failed to connect to camera",
        event_type="connection_error",
        stream_id="cam_002",
        camera_id="CAM_002",
        extra={"error_code": "CONN_TIMEOUT", "retry_count": 3}
    )
    
    # Test PTZ events
    log_event(
        logger, "info", 
        "PTZ movement executed",
        event_type="ptz_move",
        stream_id="cam_003",
        camera_id="CAM_003",
        extra={"direction": "up", "speed": 50}
    )
    
    print("\n=== Testing Exception Logging ===")
    try:
        raise ValueError("This is a test exception")
    except Exception as e:
        logger.exception("Exception occurred during processing")
    
    print("\n=== Testing Custom Logger Names ===")
    stream_logger = get_logger("StreamManager.cam_001")
    stream_logger.info("Stream manager initialized")
    
    event_logger = get_logger("EventProcessor")
    event_logger.warning("Event processing queue is full")
    
    print("\nJSON logging test completed!")

def test_plain_logging():
    """Test plain text logging for comparison."""
    print("\n\n=== Testing Plain Text Logging (for comparison) ===")
    setup_logging(level="INFO", enable_json=False)
    
    logger = get_logger("plain_logger")
    logger.info("This is plain text logging")
    logger.warning("This is a plain text warning")
    
    log_event(
        logger, "info", 
        "Stream event in plain text",
        event_type="stream_start",
        stream_id="cam_001"
    )

if __name__ == "__main__":
    test_json_logging()
    test_plain_logging()