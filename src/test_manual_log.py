#!/usr/bin/env python3
"""Manual test to insert a log entry and test API."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from main.logs.models import LogEntry

def test_manual_log_insertion():
    """Test manual log insertion and retrieval."""
    
    try:
        log_entry = LogEntry()
        print("✅ LogEntry model initialized successfully")
        
        # Test data - use proper datetime object
        test_log = {
            'timestamp': datetime.utcnow(),
            'service': 'isafe-guard-backend',
            'level': 'INFO',
            'logger': 'test_logger',
            'message': 'Test log entry for API testing',
            'module': 'test_manual_log',
            'function': 'test_manual_log_insertion',
            'line': 20,
            'thread': 12345,
            'process': 1,
            'event_type': 'test_event'
        }
        
        # Store the log
        result = log_entry.store_log(test_log)
        if result:
            print(f"✅ Log stored successfully with ID: {result}")
        else:
            print("❌ Failed to store log")
            return
        
        # Test retrieval
        logs_result = log_entry.get_logs(limit=5)
        print(f"✅ Retrieved {len(logs_result['logs'])} logs")
        print(f"   Total logs in database: {logs_result['total_count']}")
        
        if logs_result['logs']:
            latest = logs_result['logs'][0]
            print(f"   Latest log: {latest['level']} - {latest['message']}")
        
        # Test statistics
        stats = log_entry.get_log_statistics()
        print(f"✅ Statistics retrieved")
        print(f"   Total logs: {stats.get('total_logs', 0)}")
        print(f"   Error count: {stats.get('error_count', 0)}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_manual_log_insertion()