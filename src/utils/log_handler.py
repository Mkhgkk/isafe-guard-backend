import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any
from queue import Queue, Empty

from utils.logging_config import get_logger

logger = get_logger(__name__)


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler that stores logs in MongoDB."""
    
    def __init__(self, max_queue_size: int = 1000):
        super().__init__()
        self.max_queue_size = max_queue_size
        self.log_queue = Queue(maxsize=max_queue_size)
        self.stop_event = threading.Event()
        self.worker_thread = None
        self._log_entry_model = None
        
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
    
    @property
    def log_entry_model(self):
        """Lazy initialization of LogEntry model to avoid circular imports."""
        if self._log_entry_model is None:
            try:
                from main.logs.models import LogEntry
                self._log_entry_model = LogEntry()
            except Exception:
                # Database might not be ready yet, will try again later
                self._log_entry_model = None
        return self._log_entry_model
    
    def emit(self, record: logging.LogRecord):
        """Emit a log record by adding it to the queue."""
        try:
            # Convert log record to dictionary
            log_data = self._record_to_dict(record)
            
            # Add to queue (non-blocking)
            if not self.log_queue.full():
                self.log_queue.put_nowait(log_data)
            else:
                # Queue is full, drop the log (to prevent blocking)
                pass
                
        except Exception as e:
            # Don't log errors here to avoid infinite recursion
            pass
    
    def _record_to_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Convert logging record to dictionary."""
        log_data = {
            'timestamp': datetime.utcfromtimestamp(record.created),
            'service': 'isafe-guard-backend',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'process': record.process,
        }
        
        # Add exception information if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.format(record) if record.exc_text else None
            }
        
        # Add custom fields from extra
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'message', 'asctime'
            }:
                log_data[key] = value
        
        return log_data
    
    def _process_logs(self):
        """Background worker to process logs from queue."""
        while not self.stop_event.is_set():
            try:
                # Get log from queue with timeout
                log_data = self.log_queue.get(timeout=1.0)
                
                # Store in database (with error protection)
                if self.log_entry_model:
                    try:
                        self.log_entry_model.store_log(log_data)
                    except Exception:
                        # Silently ignore database storage errors to avoid recursion
                        pass
                
                # Mark task as done
                self.log_queue.task_done()
                
            except Empty:
                # No logs in queue, continue
                continue
            except Exception:
                # Error processing log, continue to avoid breaking the worker
                continue


# Global handler instance
_db_handler = None
_handler_lock = threading.Lock()


def setup_database_logging():
    """Setup database logging handler."""
    global _db_handler
    
    with _handler_lock:
        if _db_handler is None:
            try:
                _db_handler = DatabaseLogHandler()
                
                # Add to root logger
                root_logger = logging.getLogger()
                root_logger.addHandler(_db_handler)
                
                logger.info("Database logging handler initialized")
                
            except Exception as e:
                logger.error(f"Failed to setup database logging: {e}")


def get_database_handler() -> DatabaseLogHandler:
    """Get the database handler instance."""
    global _db_handler
    return _db_handler


def cleanup_database_logging():
    """Cleanup database logging handler."""
    global _db_handler
    
    with _handler_lock:
        if _db_handler:
            try:
                # Remove from root logger
                root_logger = logging.getLogger()
                root_logger.removeHandler(_db_handler)
                
                # Stop worker
                _db_handler.stop_worker()
                
                _db_handler = None
                logger.info("Database logging handler cleaned up")
                
            except Exception as e:
                logger.error(f"Failed to cleanup database logging: {e}")