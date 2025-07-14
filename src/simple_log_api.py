#!/usr/bin/env python3
"""Simple log API endpoint test."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from flask import Blueprint, request, jsonify, Flask
from database import initialize_database, get_database

# Create a test app
app = Flask(__name__)

@app.route("/test-logs", methods=["GET"])
def test_logs():
    """Simple test endpoint for logs."""
    try:
        # Initialize database
        initialize_database("mongodb://mongodb:27017/", "isafe_guard")
        db = get_database()
        logs_collection = db.logs
        
        # Get parameters
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
        level_filter = request.args.get('level')
        
        # Build query
        query = {}
        if level_filter:
            query['level'] = level_filter
        
        # Execute query
        cursor = logs_collection.find(query).sort("timestamp", -1).skip(offset).limit(limit)
        logs = list(cursor)
        
        # Get total count
        total_count = logs_collection.count_documents(query)
        
        # Convert ObjectId to string
        for log in logs:
            log['_id'] = str(log['_id'])
            if 'timestamp' in log and isinstance(log['timestamp'], datetime):
                log['timestamp'] = log['timestamp'].isoformat() + 'Z'
            if 'created_at' in log and isinstance(log['created_at'], datetime):
                log['created_at'] = log['created_at'].isoformat() + 'Z'
        
        return jsonify({
            "status": "success",
            "data": {
                "logs": logs,
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to retrieve logs: {str(e)}"
        }), 500

@app.route("/test-stats", methods=["GET"])
def test_stats():
    """Simple test endpoint for statistics."""
    try:
        # Initialize database
        initialize_database("mongodb://mongodb:27017/", "isafe_guard")
        db = get_database()
        logs_collection = db.logs
        
        # Basic stats
        total_count = logs_collection.count_documents({})
        error_count = logs_collection.count_documents({'level': 'ERROR'})
        warning_count = logs_collection.count_documents({'level': 'WARNING'})
        info_count = logs_collection.count_documents({'level': 'INFO'})
        
        # Level distribution
        level_pipeline = [
            {"$group": {"_id": "$level", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        level_stats = list(logs_collection.aggregate(level_pipeline))
        
        return jsonify({
            "status": "success",
            "data": {
                "total_logs": total_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "level_distribution": level_stats
            }
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to retrieve statistics: {str(e)}"
        }), 500

if __name__ == "__main__":
    print("Starting simple log API test server...")
    app.run(host="0.0.0.0", port=5001, debug=True)