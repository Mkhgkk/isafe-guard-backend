# rabbitmq/consumers.py
import json
import logging
import base64
import threading
import time
import uuid
from typing import Callable, Dict
import pika
from bson import ObjectId
import numpy as np
import cv2

from .connection import RabbitMQConnection
from main.event.model import Event
from utils.notifications import send_email_notification, send_watch_notification
from socket_.socketio_instance import socketio

class BaseConsumer:
    def __init__(self, queue_name: str, callback: Callable):
        self.queue_name = queue_name
        self.callback = callback
        self.running = False
        self.consumer_thread = None
        self.connection = None
        self.channel = None
        self.consumer_tag = None
        self._consumer_id = str(uuid.uuid4())[:8]
    
    def start(self):
        """Start consuming messages"""
        self.running = True
        self.consumer_thread = threading.Thread(target=self._consume, daemon=True)
        self.consumer_thread.start()
        logging.info(f"Started consumer for queue: {self.queue_name} (ID: {self._consumer_id})")
    
    def stop(self):
        """Stop consuming messages"""
        self.running = False
        
        # Stop consuming gracefully
        if self.channel and not self.channel.is_closed:
            try:
                if self.consumer_tag:
                    self.channel.basic_cancel(self.consumer_tag)
                self.channel.stop_consuming()
            except Exception as e:
                logging.warning(f"Error stopping consumer {self.queue_name}: {e}")
        
        # Close connections
        self._close_connections()
        
        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)
        logging.info(f"Stopped consumer for queue: {self.queue_name}")
    
    def _close_connections(self):
        """Close channel and connection"""
        try:
            if self.channel and not self.channel.is_closed:
                self.channel.close()
        except Exception as e:
            logging.warning(f"Error closing channel: {e}")
        
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            logging.warning(f"Error closing connection: {e}")
        
        self.channel = None
        self.connection = None
        self.consumer_tag = None
    
    def _setup_connection(self):
        """Setup a new connection for this consumer"""
        try:
            # Create new connection for this consumer
            rabbitmq = RabbitMQConnection()
            self.connection, self.channel = rabbitmq.create_new_connection()
            
            # Set QoS
            self.channel.basic_qos(prefetch_count=1)
            
            # Generate unique consumer tag
            self.consumer_tag = f"consumer-{self.queue_name}-{self._consumer_id}-{int(time.time())}"
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to setup connection for {self.queue_name}: {e}")
            self._close_connections()
            return False
    
    def _consume(self):
        """Main consume loop with error handling and reconnection"""
        retry_count = 0
        max_retries = 5
        
        while self.running:
            try:
                # Setup connection
                if not self._setup_connection():
                    retry_count += 1
                    if retry_count >= max_retries:
                        logging.error(f"Max retries reached for consumer {self.queue_name}")
                        break
                    
                    wait_time = min(retry_count * 2, 30)  # Cap at 30 seconds
                    logging.warning(f"Retrying connection for {self.queue_name} in {wait_time}s (attempt {retry_count})")
                    time.sleep(wait_time)
                    continue
                
                # Reset retry count on successful connection
                retry_count = 0
                
                # Start consuming
                self.channel.basic_consume(
                    queue=self.queue_name,
                    on_message_callback=self._message_callback,
                    auto_ack=False,
                    consumer_tag=self.consumer_tag
                )
                
                logging.info(f"Consumer {self.consumer_tag} waiting for messages on {self.queue_name}")
                self.channel.start_consuming()
                
            except pika.exceptions.AMQPConnectionError as e:
                logging.error(f"AMQP Connection error in consumer {self.queue_name}: {e}")
                self._close_connections()
                if self.running:
                    time.sleep(5)
            except Exception as e:
                logging.error(f"Error in consumer {self.queue_name}: {e}")
                self._close_connections()
                if self.running:
                    retry_count += 1
                    wait_time = min(retry_count * 2, 30)
                    time.sleep(wait_time)
    
    def _message_callback(self, channel, method, properties, body):
        """Handle incoming message"""
        try:
            # Parse message
            if properties and properties.content_type == 'application/json':
                message = json.loads(body.decode('utf-8'))
            else:
                message = body
            
            # Process message
            success = self.callback(message)
            
            # Acknowledge message
            if success:
                channel.basic_ack(delivery_tag=method.delivery_tag)
            else:
                # Reject and requeue if processing failed
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                
        except Exception as e:
            logging.error(f"Error processing message in {self.queue_name}: {e}")
            try:
                # Reject message without requeue to avoid infinite loop
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            except Exception as ack_error:
                logging.error(f"Error acknowledging message: {ack_error}")


class EventSaveConsumer(BaseConsumer):
    def __init__(self):
        super().__init__('events.save', self._process_event_save)
    
    def _process_event_save(self, message: Dict) -> bool:
        """Process event save message"""
        try:
            # Decode frame data
            frame_data = base64.b64decode(message['frame_data'])
            frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
            
            # Save event
            Event.save(
                stream_id=message['stream_id'],
                frame=frame,
                reasons=message['reasons'],
                model_name=message['model_name'],
                timestamp=message['timestamp'],
                video_name=message['video_name'],
                event_id=ObjectId(message['event_id'])
            )
            
            logging.info(f"Saved event {message['event_id']} for stream {message['stream_id']}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to save event: {e}")
            return False


class EmailNotificationConsumer(BaseConsumer):
    def __init__(self):
        super().__init__('notifications.email', self._process_email_notification)
    
    def _process_email_notification(self, message: Dict) -> bool:
        """Process email notification message"""
        try:
            send_email_notification(
                reasons=message['reasons'],
                event_id=ObjectId(message['event_id']),
                stream_id=message['stream_id']
            )
            logging.info(f"Sent email notification for event {message['event_id']}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to send email notification: {e}")
            return False


class WatchNotificationConsumer(BaseConsumer):
    def __init__(self):
        super().__init__('notifications.watch', self._process_watch_notification)
    
    def _process_watch_notification(self, message: Dict) -> bool:
        """Process watch notification message"""
        try:
            send_watch_notification(reasons=message['reasons'])
            logging.info("Sent watch notification")
            return True
            
        except Exception as e:
            logging.error(f"Failed to send watch notification: {e}")
            return False


class WebSocketNotificationConsumer(BaseConsumer):
    def __init__(self):
        super().__init__('notifications.websocket', self._process_websocket_notification)
        self.NAMESPACE = "/default"
    
    def _process_websocket_notification(self, message: Dict) -> bool:
        """Process websocket notification message"""
        try:
            socketio.emit(
                f"alert-{message['stream_id']}", 
                message['data'], 
                namespace=self.NAMESPACE, 
                room=message['stream_id']
            )
            logging.debug(f"Sent websocket alert for stream {message['stream_id']}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to send websocket notification: {e}")
            return False


class VideoProcessingConsumer(BaseConsumer):
    def __init__(self):
        super().__init__('events.video', self._process_video)
    
    def _process_video(self, message: Dict) -> bool:
        """Process video recording message"""
        try:
            # This would handle video processing logic
            # For now, just log the message
            logging.info(f"Processing video {message['video_name']} for stream {message['stream_id']}")
            
            # Decode frame if needed
            if 'frame_data' in message:
                frame_data = base64.b64decode(message['frame_data'])
                # Process frame for video recording
                
            return True
            
        except Exception as e:
            logging.error(f"Failed to process video: {e}")
            return False