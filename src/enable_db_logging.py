#!/usr/bin/env python3
"""Enable database logging in the running application."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from utils.logging_config import get_logger, log_event

def test_logging_integration():
    """Test logging integration by making API calls and generating logs."""
    
    logger = get_logger("logging_test")
    
    print("🔄 Testing logging integration...")
    
    # Generate some test logs
    logger.info("Testing logging integration started")
    
    log_event(
        logger, "info", 
        "API testing in progress", 
        event_type="api_test",
        extra={"test_id": "integration_001"}
    )
    
    # Make some API calls to generate logs
    base_url = "http://localhost:5000"
    
    try:
        # Test different endpoints
        endpoints = [
            "/api/logs/levels",
            "/api/logs/simple/stats", 
            "/api/logs/event-types",
            "/api/logs/streams"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=5)
                if response.status_code == 200:
                    log_event(
                        logger, "info", 
                        f"API endpoint {endpoint} responded successfully",
                        event_type="api_success",
                        extra={"endpoint": endpoint, "status_code": response.status_code}
                    )
                else:
                    log_event(
                        logger, "warning", 
                        f"API endpoint {endpoint} returned status {response.status_code}",
                        event_type="api_warning",
                        extra={"endpoint": endpoint, "status_code": response.status_code}
                    )
            except Exception as e:
                log_event(
                    logger, "error", 
                    f"Failed to call API endpoint {endpoint}: {str(e)}",
                    event_type="api_error",
                    extra={"endpoint": endpoint, "error": str(e)}
                )
        
        # Generate some more test events
        log_event(
            logger, "info", 
            "Simulated detection event", 
            event_type="detection",
            stream_id="cam_001",
            detection_type="person",
            confidence=0.87
        )
        
        log_event(
            logger, "warning", 
            "Simulated system warning", 
            event_type="system_warning",
            extra={"cpu_usage": 85.3, "memory_usage": 78.2}
        )
        
        logger.info("Testing logging integration completed")
        
        print("✅ Generated multiple test log entries")
        print("🔄 Check the API to see if logs are being saved...")
        
        # Wait a moment then check the stats
        import time
        time.sleep(2)
        
        try:
            response = requests.get(f"{base_url}/api/logs/simple/stats")
            if response.status_code == 200:
                stats = response.json()
                total_logs = stats['data']['total_logs']
                print(f"📊 Current total logs in database: {total_logs}")
                
                if total_logs > 6:  # More than our initial test logs
                    print("🎉 SUCCESS: New logs are being automatically saved!")
                    return True
                else:
                    print("⚠️  No new logs detected - automatic saving may not be active")
                    return False
            else:
                print(f"❌ Failed to get stats: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Error checking stats: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_logging_integration()
    print(f"\n{'✅ Integration test PASSED!' if success else '❌ Integration test FAILED!'}")