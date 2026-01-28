import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from queue import Queue, Empty
from bson import ObjectId


class DatabaseLogHandler(logging.Handler):
    """Simplified database logging handler that stores logs in MongoDB."""
    
    def __init__(self, max_queue_size: int = 1000):
        super().__init__()
        self.max_queue_size = max_queue_size
        self.log_queue = Queue(maxsize=max_queue_size)
        self.stop_event = threading.Event()
        self.worker_thread = None
        self._db_collection = None
        self._db_initialized = False
        
        # Start background worker
        self.start_worker()
    
    def start_worker(self):
        """Start the background worker thread."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._process_logs, daemon=True)
            self.worker_thread.start()
    
    def stop_worker(self):
        """Stop the background worker thread."""
        self.stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)

    def close(self):
        """Close the handler and stop the worker thread."""
        self.stop_worker()
        super().close()
    
    @property
    def db_collection(self):
        """Lazy initialization of database collection."""
        if not self._db_initialized:
            try:
                from database import get_database
                db = get_database()
                self._db_collection = db.logs
                self._db_initialized = True
            except Exception:
                # Database not ready yet, will try again later
                self._db_collection = None
                self._db_initialized = False
        return self._db_collection
    
    def emit(self, record: logging.LogRecord):
        """Emit a log record by adding it to the queue."""
        try:
            # Convert log record to dictionary
            log_data = self._record_to_dict(record)
            
            # Add to queue (non-blocking)
            if not self.log_queue.full():
                self.log_queue.put_nowait(log_data)
        except Exception:
            # Silently ignore errors to prevent logging recursion
            pass
    
    def _record_to_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Convert logging record to dictionary for MongoDB storage."""
        try:
            # Basic log data
            log_data = {
                '_id': ObjectId(),
                'timestamp': datetime.utcfromtimestamp(record.created),
                'created_at': datetime.utcnow(),
                'service': 'isafe-guard-backend',
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': getattr(record, 'module', 'unknown'),
                'function': getattr(record, 'funcName', 'unknown'),
                'line': getattr(record, 'lineno', 0),
                'thread': getattr(record, 'thread', 0),
                'process': getattr(record, 'process', 0),
            }
            
            # Add exception information if present
            if record.exc_info and record.exc_info[0] is not None:
                log_data['exception'] = {
                    'type': record.exc_info[0].__name__,
                    'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                    'traceback': self.formatException(record.exc_info) if record.exc_text else None
                }
            
            # Add custom fields from extra (this includes our structured data)
            excluded_keys = {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'message', 'asctime', 'taskName'
            }
            
            for key, value in record.__dict__.items():
                if key not in excluded_keys and not key.startswith('_'):
                    # Safely add the custom field
                    try:
                        # Convert complex objects to strings for MongoDB storage
                        if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
                            log_data[key] = value
                        else:
                            log_data[key] = str(value)
                    except Exception:
                        # Skip fields that can't be serialized
                        continue
            
            return log_data
            
        except Exception:
            # Return basic log data if conversion fails
            return {
                '_id': ObjectId(),
                'timestamp': datetime.utcnow(),
                'created_at': datetime.utcnow(),
                'service': 'isafe-guard-backend',
                'level': 'ERROR',
                'logger': 'database_log_handler',
                'message': 'Failed to convert log record',
                'module': 'database_log_handler',
                'function': '_record_to_dict',
                'line': 0,
                'thread': 0,
                'process': 0,
            }
    
    def _process_logs(self):
        """Background worker to process logs from queue."""
        while not self.stop_event.is_set():
            try:
                # Get log from queue with timeout
                log_data = self.log_queue.get(timeout=1.0)
                
                # Store in database if available
                if self.db_collection is not None:
                    try:
                        self.db_collection.insert_one(log_data)
                    except Exception:
                        # Silently ignore database errors to avoid recursion
                        pass
                
                # Mark task as done
                self.log_queue.task_done()
                
            except Empty:
                # No logs in queue, continue
                continue
            except Exception:
                # Error processing log, continue to avoid breaking the worker
                continue


# Global instance management
_handler_instance = None
_handler_lock = threading.Lock()


def get_database_log_handler():
    """Get or create the global database log handler instance."""
    global _handler_instance
    
    with _handler_lock:
        if _handler_instance is None:
            _handler_instance = DatabaseLogHandler()
    
    return _handler_instance


def setup_database_logging():
    """Setup database logging by adding handler to root logger."""
    try:
        handler = get_database_log_handler()
        
        # Add to root logger if not already added
        root_logger = logging.getLogger()
        if handler not in root_logger.handlers:
            root_logger.addHandler(handler)
            return True
        return False
    except Exception:
        return False


def cleanup_database_logging():
    """Remove database logging handler."""
    global _handler_instance
    
    with _handler_lock:
        if _handler_instance is not None:
            try:
                root_logger = logging.getLogger()
                if _handler_instance in root_logger.handlers:
                    root_logger.removeHandler(_handler_instance)
                
                _handler_instance.stop_worker()
                _handler_instance = None
                return True
            except Exception:
                pass
    
    return False