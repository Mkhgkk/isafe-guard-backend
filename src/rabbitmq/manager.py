# rabbitmq/manager.py
import logging
import atexit
import time
import threading
from typing import List
from .connection import RabbitMQConnection
from .publisher import MessagePublisher
from .consumers import (
    EventSaveConsumer, 
    EmailNotificationConsumer, 
    WatchNotificationConsumer,
    WebSocketNotificationConsumer,
    VideoProcessingConsumer,
    BaseConsumer
)

class RabbitMQManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.connection = None
            self.publisher = None
            self.consumers: List[BaseConsumer] = []
            self.is_setup = False
            self.initialized = True
            
            # Register cleanup on exit
            atexit.register(self.shutdown)
    
    def setup(self, max_retries=5, retry_delay=5):
        """Setup RabbitMQ connection and consumers with retry logic"""
        if self.is_setup:
            logging.info("RabbitMQ manager already setup")
            return
            
        for attempt in range(max_retries):
            try:
                logging.info(f"Setting up RabbitMQ manager (attempt {attempt + 1}/{max_retries})")
                
                # Create connection and setup infrastructure
                self.connection = RabbitMQConnection()
                self.connection.connect()
                
                # Wait a moment for connection to stabilize
                time.sleep(1)
                
                # Initialize publisher
                self.publisher = MessagePublisher()
                
                # Initialize consumers with delay between each
                self.consumers = []
                consumer_classes = [
                    EventSaveConsumer,
                    EmailNotificationConsumer,
                    WatchNotificationConsumer,
                    WebSocketNotificationConsumer,
                    VideoProcessingConsumer,
                ]
                
                for consumer_class in consumer_classes:
                    try:
                        consumer = consumer_class()
                        consumer.start()
                        self.consumers.append(consumer)
                        
                        # Small delay between starting consumers
                        time.sleep(0.5)
                        
                    except Exception as e:
                        logging.error(f"Failed to start consumer {consumer_class.__name__}: {e}")
                        # Continue with other consumers
                
                self.is_setup = True
                logging.info(f"RabbitMQ manager setup complete with {len(self.consumers)} consumers")
                return
                
            except Exception as e:
                logging.error(f"Failed to setup RabbitMQ manager (attempt {attempt + 1}): {e}")
                
                # Cleanup on failure
                self._cleanup_on_failure()
                
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logging.info(f"Retrying RabbitMQ setup in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logging.error("Max retries reached for RabbitMQ setup")
                    raise
    
    def _cleanup_on_failure(self):
        """Clean up resources on setup failure"""
        try:
            # Stop any started consumers
            for consumer in self.consumers:
                try:
                    consumer.stop()
                except Exception as e:
                    logging.warning(f"Error stopping consumer during cleanup: {e}")
            
            self.consumers = []
            
            # Disconnect connection
            if self.connection:
                try:
                    self.connection.disconnect()
                except Exception as e:
                    logging.warning(f"Error disconnecting during cleanup: {e}")
                self.connection = None
            
            self.publisher = None
            
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
    
    def shutdown(self):
        """Shutdown all consumers and connections"""
        if not self.is_setup:
            return
            
        logging.info("Shutting down RabbitMQ manager...")
        
        try:
            # Stop all consumers
            for consumer in self.consumers:
                try:
                    consumer.stop()
                except Exception as e:
                    logging.warning(f"Error stopping consumer: {e}")
            
            # Clear consumers list
            self.consumers = []
            
            # Disconnect from RabbitMQ
            if self.connection:
                try:
                    self.connection.disconnect()
                except Exception as e:
                    logging.warning(f"Error disconnecting: {e}")
                self.connection = None
            
            self.publisher = None
            self.is_setup = False
            
            logging.info("RabbitMQ manager shutdown complete")
            
        except Exception as e:
            logging.error(f"Error during RabbitMQ manager shutdown: {e}")
    
    def get_publisher(self) -> MessagePublisher:
        """Get the message publisher instance"""
        if not self.is_setup or not self.publisher:
            raise RuntimeError("RabbitMQ manager not properly setup")
        return self.publisher
    
    def is_healthy(self) -> bool:
        """Check if RabbitMQ manager is healthy"""
        if not self.is_setup:
            return False
            
        try:
            # Check connection
            if not self.connection or not self.connection.is_connected:
                return False
            
            # Check if consumers are running
            running_consumers = sum(1 for consumer in self.consumers if consumer.running)
            expected_consumers = 5  # Number of consumer types
            
            return running_consumers >= expected_consumers * 0.8  # At least 80% running
            
        except Exception as e:
            logging.error(f"Error checking RabbitMQ health: {e}")
            return False
    
    def restart_if_needed(self):
        """Restart RabbitMQ manager if it's not healthy"""
        if not self.is_healthy():
            logging.warning("RabbitMQ manager unhealthy, attempting restart...")
            try:
                self.shutdown()
                time.sleep(2)
                self.setup()
            except Exception as e:
                logging.error(f"Failed to restart RabbitMQ manager: {e}")