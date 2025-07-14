import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from marshmallow import Schema, fields, validate
from bson import ObjectId
from database import get_database
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LogEntrySchema(Schema):
    """Schema for log entry validation."""
    timestamp = fields.DateTime(required=True)
    service = fields.String(required=True)
    level = fields.String(required=True, validate=validate.OneOf(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']))
    logger = fields.String(required=True)
    message = fields.String(required=True)
    module = fields.String(required=False)
    function = fields.String(required=False)
    line = fields.Integer(required=False)
    thread = fields.Integer(required=False)
    process = fields.Integer(required=False)
    event_type = fields.String(required=False)
    stream_id = fields.String(required=False)
    camera_id = fields.String(required=False)
    detection_type = fields.String(required=False)
    confidence = fields.Float(required=False)


class LogSearchSchema(Schema):
    """Schema for log search parameters."""
    level = fields.String(validate=validate.OneOf(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']))
    logger = fields.String()
    message = fields.String()
    event_type = fields.String()
    stream_id = fields.String()
    camera_id = fields.String()
    detection_type = fields.String()
    start_time = fields.DateTime()
    end_time = fields.DateTime()
    limit = fields.Integer(validate=validate.Range(min=1, max=1000), missing=100)
    offset = fields.Integer(validate=validate.Range(min=0), missing=0)
    sort_order = fields.String(validate=validate.OneOf(['asc', 'desc']), missing='desc')


class LogEntry:
    """Model for log entry operations."""
    
    def __init__(self):
        self.db = get_database()
        self.collection = self.db.logs
        
        # Create indexes for efficient querying
        try:
            self.collection.create_index([("timestamp", -1)])
            self.collection.create_index([("level", 1), ("timestamp", -1)])
            self.collection.create_index([("logger", 1), ("timestamp", -1)])
            self.collection.create_index([("event_type", 1), ("timestamp", -1)])
            self.collection.create_index([("stream_id", 1), ("timestamp", -1)])
            self.collection.create_index([("service", 1), ("timestamp", -1)])
        except Exception as e:
            logger.warning(f"Could not create log indexes: {e}")
    
    def store_log(self, log_data: Dict[str, Any]) -> Optional[str]:
        """Store a log entry in the database."""
        try:
            # Prepare data for storage (skip strict validation for performance)
            prepared_data = dict(log_data)
            
            # Ensure timestamp is a datetime object
            if 'timestamp' in prepared_data:
                if isinstance(prepared_data['timestamp'], str):
                    # Parse ISO format timestamp
                    try:
                        prepared_data['timestamp'] = datetime.fromisoformat(
                            prepared_data['timestamp'].replace('Z', '+00:00')
                        )
                    except ValueError:
                        # Fall back to current time if parsing fails
                        prepared_data['timestamp'] = datetime.utcnow()
                elif not isinstance(prepared_data['timestamp'], datetime):
                    prepared_data['timestamp'] = datetime.utcnow()
            else:
                prepared_data['timestamp'] = datetime.utcnow()
            
            # Add metadata
            prepared_data['created_at'] = datetime.utcnow()
            prepared_data['_id'] = ObjectId()
            
            # Ensure required fields have defaults
            prepared_data.setdefault('service', 'isafe-guard-backend')
            prepared_data.setdefault('level', 'INFO')
            prepared_data.setdefault('logger', 'unknown')
            prepared_data.setdefault('message', '')
            
            # Insert into database
            result = self.collection.insert_one(prepared_data)
            return str(result.inserted_id)
            
        except Exception as e:
            # Use basic logging to avoid recursion
            print(f"Failed to store log entry: {e}")
            return None
    
    def get_logs(self, filters: Dict[str, Any] = None, limit: int = 100, 
                 offset: int = 0, sort_order: str = 'desc') -> Dict[str, Any]:
        """Retrieve logs with filters and pagination."""
        try:
            # Build query
            query = self._build_query(filters or {})
            
            # Set sort order
            sort_direction = -1 if sort_order == 'desc' else 1
            
            # Execute query with pagination
            cursor = self.collection.find(query).sort("timestamp", sort_direction).skip(offset).limit(limit)
            logs = list(cursor)
            
            # Get total count
            total_count = self.collection.count_documents(query)
            
            # Convert ObjectId to string for JSON serialization
            for log in logs:
                log['_id'] = str(log['_id'])
                if 'timestamp' in log and isinstance(log['timestamp'], datetime):
                    log['timestamp'] = log['timestamp'].isoformat() + 'Z'
                if 'created_at' in log and isinstance(log['created_at'], datetime):
                    log['created_at'] = log['created_at'].isoformat() + 'Z'
            
            return {
                'logs': logs,
                'total_count': total_count,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total_count
            }
            
        except Exception as e:
            logger.error(f"Failed to retrieve logs: {e}")
            return {'logs': [], 'total_count': 0, 'limit': limit, 'offset': offset, 'has_more': False}
    
    def get_log_statistics(self, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get log statistics and aggregations."""
        try:
            query = self._build_query(filters or {})
            
            # Level distribution
            level_pipeline = [
                {"$match": query},
                {"$group": {"_id": "$level", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            level_stats = list(self.collection.aggregate(level_pipeline))
            
            # Event type distribution
            event_pipeline = [
                {"$match": {**query, "event_type": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20}
            ]
            event_stats = list(self.collection.aggregate(event_pipeline))
            
            # Stream distribution
            stream_pipeline = [
                {"$match": {**query, "stream_id": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": "$stream_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20}
            ]
            stream_stats = list(self.collection.aggregate(stream_pipeline))
            
            # Recent activity (last 24 hours by hour)
            from datetime import timedelta
            now = datetime.utcnow()
            day_ago = now - timedelta(days=1)
            
            activity_pipeline = [
                {"$match": {**query, "timestamp": {"$gte": day_ago}}},
                {"$group": {
                    "_id": {
                        "year": {"$year": "$timestamp"},
                        "month": {"$month": "$timestamp"},
                        "day": {"$dayOfMonth": "$timestamp"},
                        "hour": {"$hour": "$timestamp"}
                    },
                    "count": {"$sum": 1}
                }},
                {"$sort": {"_id": 1}}
            ]
            activity_stats = list(self.collection.aggregate(activity_pipeline))
            
            # Total counts
            total_count = self.collection.count_documents(query)
            error_count = self.collection.count_documents({**query, "level": "ERROR"})
            warning_count = self.collection.count_documents({**query, "level": "WARNING"})
            
            return {
                'total_logs': total_count,
                'error_count': error_count,
                'warning_count': warning_count,
                'level_distribution': level_stats,
                'event_type_distribution': event_stats,
                'stream_distribution': stream_stats,
                'recent_activity': activity_stats
            }
            
        except Exception as e:
            logger.error(f"Failed to get log statistics: {e}")
            return {}
    
    def _build_query(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Build MongoDB query from filters."""
        query = {}
        
        if 'level' in filters:
            query['level'] = filters['level']
        
        if 'logger' in filters:
            query['logger'] = {"$regex": filters['logger'], "$options": "i"}
        
        if 'message' in filters:
            query['message'] = {"$regex": filters['message'], "$options": "i"}
        
        if 'event_type' in filters:
            query['event_type'] = filters['event_type']
        
        if 'stream_id' in filters:
            query['stream_id'] = filters['stream_id']
        
        if 'camera_id' in filters:
            query['camera_id'] = filters['camera_id']
        
        if 'detection_type' in filters:
            query['detection_type'] = filters['detection_type']
        
        # Time range filtering
        time_query = {}
        if 'start_time' in filters:
            time_query['$gte'] = filters['start_time']
        if 'end_time' in filters:
            time_query['$lte'] = filters['end_time']
        
        if time_query:
            query['timestamp'] = time_query
        
        return query
    
    def delete_old_logs(self, days_to_keep: int = 30) -> int:
        """Delete logs older than specified days."""
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            result = self.collection.delete_many({"timestamp": {"$lt": cutoff_date}})
            
            if result.deleted_count > 0:
                logger.info(f"Deleted {result.deleted_count} old log entries")
            
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Failed to delete old logs: {e}")
            return 0