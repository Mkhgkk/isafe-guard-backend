#!/usr/bin/env python3
"""Test script for the Log API endpoints."""

import requests
import json
import time
from datetime import datetime, timedelta
from utils.logging_config import setup_logging, get_logger, log_event

def test_log_api():
    """Test all log API endpoints."""
    
    # Setup logging to generate test data
    setup_logging(level="INFO", enable_json=True)
    logger = get_logger("test_api")
    
    base_url = "http://localhost:5000/api/logs"
    
    print("🧪 Testing Log API Endpoints")
    print("=" * 50)
    
    # Generate some test logs
    print("📝 Generating test log data...")
    
    # Generate various types of logs
    logger.info("Test API started")
    log_event(logger, "info", "Stream started successfully", 
              event_type="stream_start", stream_id="test_cam_001")
    log_event(logger, "warning", "High CPU usage detected", 
              event_type="system_warning", cpu_usage=85.5)
    log_event(logger, "error", "Failed to connect to camera", 
              event_type="connection_error", stream_id="test_cam_002", 
              error_code="TIMEOUT")
    log_event(logger, "info", "Person detected in restricted area", 
              event_type="detection", stream_id="test_cam_001", 
              detection_type="person", confidence=0.92)
    
    # Wait a moment for logs to be processed
    time.sleep(2)
    
    # Test 1: Get recent logs
    print("\n1️⃣ Testing GET /api/logs/recent")
    try:
        response = requests.get(f"{base_url}/recent")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: Found {len(data['data']['logs'])} recent logs")
            print(f"   Total logs in database: {data['data']['total_count']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 2: Get logs with filtering
    print("\n2️⃣ Testing GET /api/logs/ with filters")
    try:
        params = {
            'level': 'ERROR',
            'limit': 10,
            'sort_order': 'desc'
        }
        response = requests.get(f"{base_url}/", params=params)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: Found {len(data['data']['logs'])} error logs")
            if data['data']['logs']:
                latest_error = data['data']['logs'][0]
                print(f"   Latest error: {latest_error['message']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 3: Search logs with message filter
    print("\n3️⃣ Testing log search with message filter")
    try:
        params = {
            'message': 'detection',
            'limit': 5
        }
        response = requests.get(f"{base_url}/", params=params)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: Found {len(data['data']['logs'])} detection logs")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 4: Get log statistics
    print("\n4️⃣ Testing GET /api/logs/statistics")
    try:
        response = requests.get(f"{base_url}/statistics")
        if response.status_code == 200:
            data = response.json()
            stats = data['data']
            print(f"✅ Success: Retrieved log statistics")
            print(f"   Total logs: {stats.get('total_logs', 0)}")
            print(f"   Error count: {stats.get('error_count', 0)}")
            print(f"   Warning count: {stats.get('warning_count', 0)}")
            
            if stats.get('level_distribution'):
                print("   Level distribution:")
                for level_stat in stats['level_distribution']:
                    print(f"     {level_stat['_id']}: {level_stat['count']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 5: Advanced search via POST
    print("\n5️⃣ Testing POST /api/logs/search")
    try:
        search_data = {
            'event_type': 'detection',
            'limit': 10,
            'sort_order': 'desc'
        }
        response = requests.post(f"{base_url}/search", 
                               json=search_data,
                               headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: Found {len(data['data']['logs'])} detection events")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 6: Get available event types
    print("\n6️⃣ Testing GET /api/logs/event-types")
    try:
        response = requests.get(f"{base_url}/event-types")
        if response.status_code == 200:
            data = response.json()
            event_types = data['data']['event_types']
            print(f"✅ Success: Found {len(event_types)} event types")
            print(f"   Event types: {', '.join(event_types[:10])}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 7: Get stream information
    print("\n7️⃣ Testing GET /api/logs/streams")
    try:
        response = requests.get(f"{base_url}/streams")
        if response.status_code == 200:
            data = response.json()
            streams = data['data']['streams']
            print(f"✅ Success: Found {len(streams)} streams with logs")
            for stream in streams[:5]:  # Show first 5
                print(f"   {stream['stream_id']}: {stream['log_count']} logs")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 8: Get available log levels
    print("\n8️⃣ Testing GET /api/logs/levels")
    try:
        response = requests.get(f"{base_url}/levels")
        if response.status_code == 200:
            data = response.json()
            levels = data['data']['levels']
            print(f"✅ Success: Available log levels: {', '.join(levels)}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 9: Time-based filtering
    print("\n9️⃣ Testing time-based filtering")
    try:
        # Get logs from last hour
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        
        params = {
            'start_time': start_time.isoformat() + 'Z',
            'end_time': end_time.isoformat() + 'Z',
            'limit': 20
        }
        response = requests.get(f"{base_url}/", params=params)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success: Found {len(data['data']['logs'])} logs from last hour")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 10: Pagination
    print("\n🔟 Testing pagination")
    try:
        # First page
        params = {'limit': 5, 'offset': 0}
        response = requests.get(f"{base_url}/", params=params)
        if response.status_code == 200:
            data = response.json()
            first_page = data['data']
            print(f"✅ First page: {len(first_page['logs'])} logs")
            print(f"   Has more: {first_page['has_more']}")
            
            # Second page
            params = {'limit': 5, 'offset': 5}
            response = requests.get(f"{base_url}/", params=params)
            if response.status_code == 200:
                data = response.json()
                second_page = data['data']
                print(f"✅ Second page: {len(second_page['logs'])} logs")
            else:
                print(f"❌ Second page failed: {response.status_code}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 Log API testing completed!")
    print("\n📋 API Endpoints Summary:")
    print(f"   GET  {base_url}/                  - Get logs with filtering")
    print(f"   GET  {base_url}/recent            - Get recent logs")
    print(f"   GET  {base_url}/statistics        - Get log statistics")
    print(f"   GET  {base_url}/levels            - Get available log levels")
    print(f"   GET  {base_url}/event-types       - Get available event types")
    print(f"   GET  {base_url}/streams           - Get stream information")
    print(f"   POST {base_url}/search            - Advanced log search")
    print(f"   POST {base_url}/cleanup           - Cleanup old logs")

if __name__ == "__main__":
    test_log_api()