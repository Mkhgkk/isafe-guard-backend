# rabbitmq/publisher.py
import json
import logging
import pickle
import base64
from datetime import datetime
from typing import Dict, Any, Optional
from .connection import RabbitMQConnection, with_rabbitmq_retry

class MessagePublisher:
    def __init__(self):
        self.rabbitmq = RabbitMQConnection()
    
    @with_rabbitmq_retry()
    def publish_event_save(self, stream_id: str, frame_data: bytes, reasons: list, 
                          model_name: str, timestamp: float, video_name: str, event_id: str):
        """Publish event save message"""
        message = {
            'stream_id': stream_id,
            'frame_data': base64.b64encode(frame_data).decode('utf-8'),
            'reasons': reasons,
            'model_name': model_name,
            'timestamp': timestamp,
            'video_name': video_name,
            'event_id': str(event_id),
            'created_at': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='events',
            routing_key='event.save',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
                content_type='application/json'
            )
        )
        logging.info(f"Published event save message for stream {stream_id}")
    
    @with_rabbitmq_retry()
    def publish_email_notification(self, reasons: list, event_id: str, stream_id: str):
        """Publish email notification message"""
        message = {
            'reasons': reasons,
            'event_id': str(event_id),
            'stream_id': stream_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='notifications',
            routing_key='notification.email',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            )
        )
        logging.info(f"Published email notification for event {event_id}")
    
    @with_rabbitmq_retry()
    def publish_watch_notification(self, reasons: list, stream_id: str = None):
        """Publish watch notification message"""
        message = {
            'reasons': reasons,
            'stream_id': stream_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='notifications',
            routing_key='notification.watch',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            )
        )
        logging.info("Published watch notification")
    
    @with_rabbitmq_retry()
    def publish_websocket_alert(self, stream_id: str, alert_type: str, data: Dict):
        """Publish websocket alert message"""
        message = {
            'stream_id': stream_id,
            'alert_type': alert_type,
            'data': data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='notifications',
            routing_key='notification.websocket',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                content_type='application/json'
            )
        )
        logging.debug(f"Published websocket alert for stream {stream_id}")
    
    @with_rabbitmq_retry()
    def publish_video_processing(self, stream_id: str, frame_data: bytes, 
                                video_name: str, process_config: Dict):
        """Publish video processing message"""
        message = {
            'stream_id': stream_id,
            'frame_data': base64.b64encode(frame_data).decode('utf-8'),
            'video_name': video_name,
            'process_config': process_config,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='events',
            routing_key='event.video',
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            )
        )
        logging.info(f"Published video processing message for {video_name}")
    
    @with_rabbitmq_retry()
    def publish_health_status(self, stream_id: str, status: str, metrics: Dict):
        """Publish health status message"""
        message = {
            'stream_id': stream_id,
            'status': status,
            'metrics': metrics,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        channel = self.rabbitmq.get_channel()
        channel.basic_publish(
            exchange='health',
            routing_key='',  # fanout exchange doesn't use routing key
            body=json.dumps(message),
            properties=pika.BasicProperties(
                content_type='application/json'
            )
        )