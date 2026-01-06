from datetime import datetime
from flask import Blueprint, request, jsonify
from marshmallow import ValidationError
from main import tools
from main.logs.models import LogEntry, LogSearchSchema
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)

logs_blueprint = Blueprint("logs", __name__)


@logs_blueprint.route("/", methods=["GET"])
def get_logs():
    """Get logs with optional filtering and pagination
    ---
    tags:
      - Logs
    parameters:
      - in: query
        name: level
        type: string
        required: false
        description: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
      - in: query
        name: logger
        type: string
        required: false
        description: Logger name (supports partial matching)
      - in: query
        name: message
        type: string
        required: false
        description: Message content (supports partial matching)
      - in: query
        name: event_type
        type: string
        required: false
        description: Event type filter
      - in: query
        name: stream_id
        type: string
        required: false
        description: Stream ID filter
      - in: query
        name: start_time
        type: string
        required: false
        description: Start time (ISO format)
      - in: query
        name: end_time
        type: string
        required: false
        description: End time (ISO format)
      - in: query
        name: limit
        type: integer
        required: false
        default: 100
        description: Number of logs to return (max 1000)
      - in: query
        name: offset
        type: integer
        required: false
        default: 0
        description: Number of logs to skip
      - in: query
        name: sort_order
        type: string
        required: false
        default: desc
        description: Sort order (asc/desc)
    responses:
      200:
        description: Logs retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                logs:
                  type: array
                  items:
                    type: object
                total_count:
                  type: integer
      400:
        description: Invalid parameters
    """
    try:
        # Validate query parameters
        schema = LogSearchSchema()
        filters = schema.load(request.args)
        
        # Get logs
        log_entry = LogEntry()
        result = log_entry.get_logs(
            filters=filters,
            limit=filters.get('limit', 100),
            offset=filters.get('offset', 0),
            sort_order=filters.get('sort_order', 'desc')
        )
        
        log_event(
            logger, "info", 
            f"Retrieved {len(result['logs'])} logs",
            event_type="logs_retrieved",
            extra={
                "total_count": result['total_count'],
                "filters_applied": len([k for k, v in filters.items() if v is not None])
            }
        )
        
        return tools.JsonResp({
            "status": "success",
            "data": result
        }, 200)
        
    except ValidationError as e:
        log_event(
            logger, "warning", 
            "Invalid log search parameters",
            event_type="validation_error",
            extra={"errors": e.messages}
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Invalid parameters",
            "errors": e.messages
        }, 400)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to retrieve logs: {str(e)}",
            event_type="logs_retrieval_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to retrieve logs"
        }, 500)


@logs_blueprint.route("/statistics", methods=["GET"])
def get_log_statistics():
    """Get log statistics and aggregations
    ---
    tags:
      - Logs
    parameters:
      - in: query
        name: level
        type: string
        required: false
        description: Filter by log level
      - in: query
        name: start_time
        type: string
        required: false
        description: Start time for statistics (ISO format)
      - in: query
        name: end_time
        type: string
        required: false
        description: End time for statistics (ISO format)
      - in: query
        name: stream_id
        type: string
        required: false
        description: Filter by stream ID
      - in: query
        name: event_type
        type: string
        required: false
        description: Filter by event type
    responses:
      200:
        description: Log statistics retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                total_logs:
                  type: integer
                by_level:
                  type: object
                by_event_type:
                  type: object
      400:
        description: Invalid parameters
    """
    try:
        # Parse filters (reuse search schema but make everything optional)
        filters = {}
        
        if request.args.get('level'):
            filters['level'] = request.args.get('level')
        if request.args.get('stream_id'):
            filters['stream_id'] = request.args.get('stream_id')
        if request.args.get('event_type'):
            filters['event_type'] = request.args.get('event_type')
        if request.args.get('start_time'):
            try:
                filters['start_time'] = datetime.fromisoformat(request.args.get('start_time').replace('Z', '+00:00'))
            except ValueError:
                return tools.JsonResp({
                    "status": "error",
                    "message": "Invalid start_time format. Use ISO format."
                }, 400)
        if request.args.get('end_time'):
            try:
                filters['end_time'] = datetime.fromisoformat(request.args.get('end_time').replace('Z', '+00:00'))
            except ValueError:
                return tools.JsonResp({
                    "status": "error",
                    "message": "Invalid end_time format. Use ISO format."
                }, 400)
        
        # Get statistics
        log_entry = LogEntry()
        stats = log_entry.get_log_statistics(filters)
        
        log_event(
            logger, "info", 
            "Retrieved log statistics",
            event_type="log_statistics_retrieved",
            extra={
                "total_logs": stats.get('total_logs', 0),
                "filters_applied": len(filters)
            }
        )
        
        return tools.JsonResp({
            "status": "success",
            "data": stats
        }, 200)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to retrieve log statistics: {str(e)}",
            event_type="log_statistics_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to retrieve log statistics"
        }, 500)


@logs_blueprint.route("/levels", methods=["GET"])
def get_log_levels():
    """Get available log levels."""
    return tools.JsonResp({
        "status": "success",
        "data": {
            "levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        }
    }, 200)


@logs_blueprint.route("/event-types", methods=["GET"])
def get_event_types():
    """Get available event types from recent logs."""
    try:
        log_entry = LogEntry()
        
        # Get distinct event types from recent logs
        from database import get_database
        db = get_database()
        
        pipeline = [
            {"$match": {"event_type": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$event_type"}},
            {"$sort": {"_id": 1}},
            {"$limit": 100}
        ]
        
        result = list(db.logs.aggregate(pipeline))
        event_types = [item['_id'] for item in result]
        
        return tools.JsonResp({
            "status": "success",
            "data": {
                "event_types": event_types
            }
        }, 200)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to retrieve event types: {str(e)}",
            event_type="event_types_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to retrieve event types"
        }, 500)


@logs_blueprint.route("/streams", methods=["GET"])
def get_log_streams():
    """Get available stream IDs from recent logs."""
    try:
        log_entry = LogEntry()
        
        # Get distinct stream IDs from recent logs
        from database import get_database
        db = get_database()
        
        pipeline = [
            {"$match": {"stream_id": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$stream_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 50}
        ]
        
        result = list(db.logs.aggregate(pipeline))
        streams = [{"stream_id": item['_id'], "log_count": item['count']} for item in result]
        
        return tools.JsonResp({
            "status": "success",
            "data": {
                "streams": streams
            }
        }, 200)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to retrieve log streams: {str(e)}",
            event_type="log_streams_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to retrieve log streams"
        }, 500)


@logs_blueprint.route("/recent", methods=["GET"])
def get_recent_logs():
    """Get recent logs (last 100 entries)
    ---
    tags:
      - Logs
    responses:
      200:
        description: Recent logs retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                logs:
                  type: array
                  items:
                    type: object
                total_count:
                  type: integer
    """
    try:
        log_entry = LogEntry()
        result = log_entry.get_logs(
            filters={},
            limit=100,
            offset=0,
            sort_order='desc'
        )
        
        return tools.JsonResp({
            "status": "success",
            "data": result
        }, 200)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to retrieve recent logs: {str(e)}",
            event_type="recent_logs_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to retrieve recent logs"
        }, 500)


@logs_blueprint.route("/search", methods=["POST"])
def search_logs():
    """
    Advanced log search with JSON body.
    
    Body should contain search parameters similar to GET /logs
    but allows for more complex queries.
    """
    try:
        # Get JSON data
        data = request.get_json() or {}
        
        # Validate search parameters
        schema = LogSearchSchema()
        filters = schema.load(data)
        
        # Get logs
        log_entry = LogEntry()
        result = log_entry.get_logs(
            filters=filters,
            limit=filters.get('limit', 100),
            offset=filters.get('offset', 0),
            sort_order=filters.get('sort_order', 'desc')
        )
        
        log_event(
            logger, "info", 
            f"Performed advanced log search, found {len(result['logs'])} logs",
            event_type="log_search_performed",
            extra={
                "total_count": result['total_count'],
                "search_criteria": filters
            }
        )
        
        return tools.JsonResp({
            "status": "success",
            "data": result
        }, 200)
        
    except ValidationError as e:
        log_event(
            logger, "warning", 
            "Invalid log search criteria",
            event_type="validation_error",
            extra={"errors": e.messages}
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Invalid search criteria",
            "errors": e.messages
        }, 400)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to perform log search: {str(e)}",
            event_type="log_search_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to perform log search"
        }, 500)


@logs_blueprint.route("/cleanup", methods=["POST"])
def cleanup_old_logs():
    """
    Delete old logs to free up space.
    
    Body:
    - days_to_keep: Number of days to keep (default 30)
    """
    try:
        data = request.get_json() or {}
        days_to_keep = data.get('days_to_keep', 30)
        
        if not isinstance(days_to_keep, int) or days_to_keep < 1:
            return tools.JsonResp({
                "status": "error",
                "message": "days_to_keep must be a positive integer"
            }, 400)
        
        log_entry = LogEntry()
        deleted_count = log_entry.delete_old_logs(days_to_keep)
        
        log_event(
            logger, "info", 
            f"Cleaned up {deleted_count} old log entries",
            event_type="log_cleanup_performed",
            extra={
                "deleted_count": deleted_count,
                "days_to_keep": days_to_keep
            }
        )
        
        return tools.JsonResp({
            "status": "success",
            "message": f"Deleted {deleted_count} old log entries",
            "data": {
                "deleted_count": deleted_count,
                "days_to_keep": days_to_keep
            }
        }, 200)
        
    except Exception as e:
        log_event(
            logger, "error", 
            f"Failed to cleanup old logs: {str(e)}",
            event_type="log_cleanup_error"
        )
        return tools.JsonResp({
            "status": "error",
            "message": "Failed to cleanup old logs"
        }, 500)