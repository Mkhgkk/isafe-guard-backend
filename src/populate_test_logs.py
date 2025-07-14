#!/usr/bin/env python3
"""Populate database with test logs to demonstrate the API."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from database import initialize_database, get_database
from bson import ObjectId
import random

def populate_test_logs():
    """Insert test log data into the database."""
    
    try:
        # Initialize database connection
        initialize_database("mongodb://mongodb:27017/", "isafe_guard")
        db = get_database()
        logs_collection = db.logs
        
        print("🔄 Creating test log entries...")
        
        # Generate test logs for the last 24 hours
        now = datetime.utcnow()
        test_logs = []
        
        # Log levels and their frequencies
        levels = ['INFO', 'WARNING', 'ERROR', 'DEBUG']
        level_weights = [0.6, 0.25, 0.1, 0.05]  # INFO most common, ERROR least
        
        # Event types
        event_types = [
            'stream_start', 'stream_stop', 'detection', 'connection_error',
            'ptz_move', 'system_warning', 'validation_error', 'info'
        ]
        
        # Stream IDs
        stream_ids = ['cam_001', 'cam_002', 'cam_003', 'cam_004']
        
        # Detection types
        detection_types = ['person', 'vehicle', 'helmet', 'safety_vest']
        
        # Generate 100 test logs
        for i in range(100):
            # Random timestamp in last 24 hours
            minutes_ago = random.randint(0, 1440)  # 24 hours = 1440 minutes
            timestamp = now - timedelta(minutes=minutes_ago)
            
            # Random level
            level = random.choices(levels, weights=level_weights)[0]
            
            # Random event type
            event_type = random.choice(event_types)
            
            # Create log entry
            log_entry = {
                '_id': ObjectId(),
                'timestamp': timestamp,
                'created_at': now,
                'service': 'isafe-guard-backend',
                'level': level,
                'logger': f'test_logger_{random.randint(1, 5)}',
                'module': 'test_module',
                'function': 'test_function',
                'line': random.randint(10, 500),
                'thread': random.randint(100000, 999999),
                'process': 1,
                'event_type': event_type
            }
            
            # Add specific fields based on event type
            if event_type == 'stream_start':
                log_entry['message'] = f"Stream started successfully"
                log_entry['stream_id'] = random.choice(stream_ids)
                log_entry['camera_id'] = f"CAM_{log_entry['stream_id'][-3:]}"
                
            elif event_type == 'detection':
                detection_type = random.choice(detection_types)
                confidence = round(random.uniform(0.7, 0.99), 2)
                log_entry['message'] = f"{detection_type.title()} detected in stream"
                log_entry['stream_id'] = random.choice(stream_ids)
                log_entry['detection_type'] = detection_type
                log_entry['confidence'] = confidence
                
            elif event_type == 'connection_error':
                log_entry['message'] = "Failed to connect to camera"
                log_entry['stream_id'] = random.choice(stream_ids)
                log_entry['error_code'] = random.choice(['TIMEOUT', 'REFUSED', 'UNREACHABLE'])
                log_entry['level'] = 'ERROR'  # Force error level
                
            elif event_type == 'ptz_move':
                directions = ['up', 'down', 'left', 'right', 'zoom_in', 'zoom_out']
                direction = random.choice(directions)
                log_entry['message'] = f"PTZ camera moved {direction}"
                log_entry['stream_id'] = random.choice(stream_ids)
                log_entry['direction'] = direction
                
            elif event_type == 'system_warning':
                metrics = ['CPU usage', 'Memory usage', 'Disk space']
                metric = random.choice(metrics)
                value = random.randint(80, 95)
                log_entry['message'] = f"High {metric.lower()} detected: {value}%"
                log_entry['level'] = 'WARNING'  # Force warning level
                log_entry[metric.lower().replace(' ', '_')] = value
                
            else:
                log_entry['message'] = f"Test {event_type} event occurred"
                if random.random() < 0.5:  # 50% chance to add stream_id
                    log_entry['stream_id'] = random.choice(stream_ids)
            
            test_logs.append(log_entry)
        
        # Insert all logs
        result = logs_collection.insert_many(test_logs)
        print(f"✅ Inserted {len(result.inserted_ids)} test log entries")
        
        # Show summary
        total_count = logs_collection.count_documents({})
        error_count = logs_collection.count_documents({'level': 'ERROR'})
        warning_count = logs_collection.count_documents({'level': 'WARNING'})
        
        print(f"📊 Database Summary:")
        print(f"   Total logs: {total_count}")
        print(f"   Error logs: {error_count}")
        print(f"   Warning logs: {warning_count}")
        print(f"   Info logs: {total_count - error_count - warning_count}")
        
        print("\n🎉 Test data populated successfully!")
        print("Now you can test the API endpoints:")
        print("   curl http://localhost:5000/api/logs/recent")
        print("   curl http://localhost:5000/api/logs/statistics")
        print("   curl 'http://localhost:5000/api/logs/?level=ERROR&limit=10'")
        
    except Exception as e:
        print(f"❌ Failed to populate test logs: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    populate_test_logs()