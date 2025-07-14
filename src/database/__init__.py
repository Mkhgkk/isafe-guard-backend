from pymongo import MongoClient
from threading import Lock
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)

class MongoDatabase:
    _instance = None
    _lock = Lock()

    def __new__(cls, uri=None, db_name=None):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    if not uri or not db_name:
                        raise ValueError("MongoDatabase not initialized. Provide 'uri' and 'db_name' on first call.")
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize(uri, db_name)
        return cls._instance

    def _initialize(self, uri, db_name):
        log_event(logger, "info", f"Connecting to {uri} {db_name} database...", event_type="info")
        self.mongo_client = MongoClient(uri)
        self.db = self.mongo_client[db_name]
        log_event(logger, "info", "Connected to database.", event_type="info")

    @property
    def database(self):
        return self.db

# Initialize the singleton
def initialize_database(uri, db_name):
    """Initializes the MongoDB singleton."""
    return MongoDatabase(uri, db_name)

# Access the database instance
def get_database():
    """Returns the shared MongoDB database instance."""
    return MongoDatabase().database
