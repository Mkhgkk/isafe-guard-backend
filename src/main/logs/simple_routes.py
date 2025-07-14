from datetime import datetime
from flask import Blueprint, request, jsonify
from database import get_database

simple_logs_blueprint = Blueprint("simple_logs", __name__)


@simple_logs_blueprint.route("/simple", methods=["GET"])
def get_logs_simple():
    """Simple log retrieval without complex error handling."""
    try:
        db = get_database()
        logs_collection = db.logs
        
        # Get parameters
        limit = min(int(request.args.get('limit', 100)), 1000)
        offset = int(request.args.get('offset', 0))
        level_filter = request.args.get('level')
        event_type_filter = request.args.get('event_type')
        stream_id_filter = request.args.get('stream_id')
        
        # Build query
        query = {}
        if level_filter:
            query['level'] = level_filter
        if event_type_filter:
            query['event_type'] = event_type_filter
        if stream_id_filter:
            query['stream_id'] = stream_id_filter
        
        # Execute query
        cursor = logs_collection.find(query).sort("timestamp", -1).skip(offset).limit(limit)
        logs = list(cursor)
        
        # Get total count
        total_count = logs_collection.count_documents(query)
        
        # Convert ObjectId and datetime to string
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
            "message": f"Database error: {str(e)}"
        }), 500


@simple_logs_blueprint.route("/simple/stats", methods=["GET"])
def get_stats_simple():
    """Simple statistics retrieval."""
    try:
        db = get_database()
        logs_collection = db.logs
        
        # Basic counts
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
        
        # Event type distribution
        event_pipeline = [
            {"$match": {"event_type": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        event_stats = list(logs_collection.aggregate(event_pipeline))
        
        return jsonify({
            "status": "success",
            "data": {
                "total_logs": total_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "level_distribution": level_stats,
                "event_type_distribution": event_stats
            }
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Statistics error: {str(e)}"
        }), 500


@simple_logs_blueprint.route("/simple/recent", methods=["GET"])
def get_recent_simple():
    """Get recent logs without complex filtering."""
    try:
        db = get_database()
        logs_collection = db.logs
        
        # Get 20 most recent logs
        cursor = logs_collection.find({}).sort("timestamp", -1).limit(20)
        logs = list(cursor)
        
        # Convert ObjectId and datetime to string
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
                "count": len(logs)
            }
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Recent logs error: {str(e)}"
        }), 500