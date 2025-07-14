#!/usr/bin/env python3
"""Simple test to check database connection for logs."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import initialize_database, get_database

def test_direct_db_access():
    """Test direct database access for logs."""
    try:
        # Initialize database connection
        initialize_database("mongodb://mongodb:27017/", "isafe_guard")
        db = get_database()
        logs_collection = db.logs
        
        print("✅ Database connection successful")
        
        # Test basic query
        total_count = logs_collection.count_documents({})
        print(f"✅ Total logs in database: {total_count}")
        
        # Test retrieval
        recent_logs = list(logs_collection.find({}).sort("timestamp", -1).limit(3))
        print(f"✅ Retrieved {len(recent_logs)} recent logs")
        
        for log in recent_logs:
            print(f"   - {log.get('level', 'N/A')}: {log.get('message', 'N/A')}")
        
        # Test with filter
        error_count = logs_collection.count_documents({"level": "ERROR"})
        print(f"✅ Error logs count: {error_count}")
        
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_direct_db_access()
    print(f"\n{'✅ Database access working!' if success else '❌ Database access failed!'}")