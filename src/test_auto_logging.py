#!/usr/bin/env python3
"""Test automatic database logging functionality."""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import initialize_database, get_database
from utils.database_log_handler import setup_database_logging
from utils.logging_config import setup_logging, get_logger, log_event

def test_automatic_logging():
    """Test that logs are automatically saved to database."""
    
    try:
        # Initialize database
        initialize_database("mongodb://mongodb:27017/", "isafe_guard")
        db = get_database()
        logs_collection = db.logs
        
        print("🔄 Testing automatic database logging...")
        
        # Get initial count
        initial_count = logs_collection.count_documents({})
        print(f"📊 Initial log count: {initial_count}")
        
        # Setup logging systems
        setup_logging(level="INFO", enable_json=True)
        setup_database_logging()
        
        # Wait a moment for setup
        time.sleep(1)
        
        # Create test logger
        logger = get_logger("test_auto_logging")
        
        print("🧪 Generating test log entries...")
        
        # Generate some test logs
        logger.info("Test automatic logging - basic info message")
        
        log_event(
            logger, "info", 
            "Test stream started", 
            event_type="stream_start",
            stream_id="test_cam_001",
            camera_id="TEST_CAM_001"
        )
        
        log_event(
            logger, "warning", 
            "Test detection event", 
            event_type="detection",
            stream_id="test_cam_001",
            detection_type="person",
            confidence=0.95
        )
        
        log_event(
            logger, "error", 
            "Test connection error", 
            event_type="connection_error",
            stream_id="test_cam_002",
            extra={"error_code": "TIMEOUT", "retry_count": 3}
        )
        
        logger.warning("Test warning message")
        logger.error("Test error message")
        
        print("⏳ Waiting for background processing...")
        time.sleep(3)  # Wait for background worker to process
        
        # Check if new logs were added
        final_count = logs_collection.count_documents({})
        new_logs = final_count - initial_count
        
        print(f"📊 Final log count: {final_count}")
        print(f"✨ New logs added: {new_logs}")
        
        if new_logs > 0:
            print("✅ SUCCESS: Automatic logging is working!")
            
            # Show some recent logs
            recent_logs = list(logs_collection.find({}).sort("timestamp", -1).limit(3))
            print("\n📝 Recent log entries:")
            for log in recent_logs:
                timestamp = log.get('timestamp', 'N/A')
                level = log.get('level', 'N/A')
                message = log.get('message', 'N/A')
                event_type = log.get('event_type', 'N/A')
                print(f"   {timestamp} [{level}] {message} (event: {event_type})")
            
            return True
        else:
            print("❌ FAILED: No new logs were automatically saved")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_automatic_logging()
    print(f"\n{'🎉 Automatic logging test PASSED!' if success else '💥 Automatic logging test FAILED!'}")