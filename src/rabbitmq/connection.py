# rabbitmq/connection.py
import pika
import json
import logging
import threading
import time
import uuid
from typing import Optional, Callable
from functools import wraps

class RabbitMQConnection:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.is_connected = False
        self.host = 'rabbitmq'  # Use service name for Docker
        self.port = 5672
        self.username = 'admin'
        self.password = 'password'
        self.virtual_host = '/'
        self._lock = threading.Lock()
        self._connection_id = str(uuid.uuid4())[:8]
    
    def connect(self):
        """Establish connection to RabbitMQ server"""
        with self._lock:
            try:
                # Close existing connection if any
                if self.connection and not self.connection.is_closed:
                    try:
                        self.connection.close()
                    except:
                        pass
                
                credentials = pika.PlainCredentials(self.username, self.password)
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    virtual_host=self.virtual_host,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                    socket_timeout=10,
                    retry_delay=2,
                    connection_attempts=3
                )
                
                self.connection = pika.BlockingConnection(parameters)
                self.channel = self.connection.channel()
                self.is_connected = True
                logging.info(f"Connected to RabbitMQ (ID: {self._connection_id})")
                
                # Declare exchanges and queues
                self._setup_exchanges_and_queues()
                
            except Exception as e:
                logging.error(f"Failed to connect to RabbitMQ: {e}")
                self.is_connected = False
                self.connection = None
                self.channel = None
                raise
    
    def _setup_exchanges_and_queues(self):
        """Setup all exchanges and queues"""
        try:
            # Declare exchanges
            exchanges = [
                ('events', 'topic'),
                ('notifications', 'topic'),
                ('frames', 'direct'),
                ('health', 'fanout'),
            ]
            
            for exchange_name, exchange_type in exchanges:
                self.channel.exchange_declare(
                    exchange=exchange_name,
                    exchange_type=exchange_type,
                    durable=True
                )
            
            # Declare queues
            queues = [
                # Event processing queues
                ('events.save', True, 'events', 'event.save'),
                ('events.video', True, 'events', 'event.video'),
                
                # Notification queues
                ('notifications.email', True, 'notifications', 'notification.email'),
                ('notifications.watch', True, 'notifications', 'notification.watch'),
                ('notifications.websocket', True, 'notifications', 'notification.websocket'),
                
                # Frame processing queues
                ('frames.detection', True, 'frames', 'frames.detection'),
                ('frames.recording', True, 'frames', 'frames.recording'),
                
                # Health monitoring
                ('health.monitor', False, 'health', ''),
            ]
            
            for queue_name, durable, exchange, routing_key in queues:
                self.channel.queue_declare(queue=queue_name, durable=durable)
                if exchange and routing_key:
                    self.channel.queue_bind(
                        exchange=exchange,
                        queue=queue_name,
                        routing_key=routing_key
                    )
                elif exchange:  # fanout exchange
                    self.channel.queue_bind(exchange=exchange, queue=queue_name)
                    
        except Exception as e:
            logging.error(f"Failed to setup exchanges and queues: {e}")
            raise
    
    def disconnect(self):
        """Close connection to RabbitMQ"""
        with self._lock:
            try:
                if self.channel and not self.channel.is_closed:
                    self.channel.close()
                if self.connection and not self.connection.is_closed:
                    self.connection.close()
            except Exception as e:
                logging.warning(f"Error during disconnect: {e}")
            finally:
                self.is_connected = False
                self.connection = None
                self.channel = None
                logging.info("Disconnected from RabbitMQ")
    
    def get_channel(self):
        """Get the current channel, reconnect if necessary"""
        with self._lock:
            if not self.is_connected or not self.channel or self.channel.is_closed:
                self.connect()
            return self.channel
    
    def create_new_connection(self):
        """Create a new independent connection for consumers"""
        try:
            credentials = pika.PlainCredentials(self.username, self.password)
            parameters = pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                virtual_host=self.virtual_host,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
                socket_timeout=10,
                retry_delay=2,
                connection_attempts=3
            )
            
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            logging.info(f"Created new RabbitMQ connection")
            return connection, channel
            
        except Exception as e:
            logging.error(f"Failed to create new RabbitMQ connection: {e}")
            raise

def with_rabbitmq_retry(max_retries=3, delay=1):
    """Decorator to retry RabbitMQ operations"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logging.error(f"RabbitMQ operation failed after {max_retries} attempts: {e}")
                        raise
                    logging.warning(f"RabbitMQ operation failed (attempt {attempt + 1}): {e}")
                    time.sleep(delay * (2 ** attempt))  # Exponential backoff
            return None
        return wrapper
    return decorator