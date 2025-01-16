import os
import cv2
import json
import time
import logging
import numpy as np
from typing import List
from bson import ObjectId
from datetime import datetime
from flask import current_app as app
from flask import request
from pymongo import ASCENDING, DESCENDING
from marshmallow import Schema, fields, ValidationError, validate
from main import tools
from database import MongoDatabase, get_database
from config import STATIC_DIR


class EventSchema(Schema):
    stream_id = fields.String(required=True)
    reasons = fields.List(fields.String(), required=True)
    model_name = fields.String(required=True)
    timestamp = fields.Integer(required=True)
    thumbnail = fields.String(required=True)
    video_filename = fields.String(required=True)
    # event_type = fields.String(required=True, validate=validate.OneOf(['PPE', 'Ladder', 'Mobile Scaffolding', 'Cutting Welding']))


event_schema = EventSchema()


class Event:
    def __init__(self):
        self.collection = get_database()["events"]

    @staticmethod
    def save(
        stream_id: str,
        frame: np.ndarray,
        reasons: List[str],
        model_name: str,
        start_time: float,
        filename: str,
    ) -> None:
        EVENT_THUMBNAIL_DIR = os.path.join(STATIC_DIR, stream_id, "thumbnails")

        timestamp_str = str(int(time.time()))
        image_filename = f"thumbnail_{timestamp_str}.jpg"

        image_directory = os.path.abspath(
            os.path.join(os.path.dirname(__file__), EVENT_THUMBNAIL_DIR)
        )
        os.makedirs(image_directory, exist_ok=True)

        original_height, original_width = frame.shape[:2]
        target_width = 450
        aspect_ratio = original_height / original_width
        target_height = int(target_width * aspect_ratio)
        resized_frame = cv2.resize(
            frame, (target_width, target_height), interpolation=cv2.INTER_AREA
        )

        image_path = os.path.join(image_directory, image_filename)

        ret = cv2.imwrite(image_path, resized_frame)

        if not ret:
            logging.error("Failed to save thumbnail image.")
            return

        try:
            data = {
                "stream_id": stream_id,
                "reasons": reasons,
                "model_name": model_name,
                "timestamp": int(start_time),
                "thumbnail": image_filename,
                "video_filename": filename,
            }

            response = Event().create_event(data)
            logging.info(f"Event saved successfully: {response}")
        except Exception as e:
            logging.error(f"Error saving event to database: {e}")

    def create_event(self, data):
        errors = event_schema.validate(data)
        if errors:
            raise ValidationError(errors)

        try:
            event = self.collection.insert_one(data)
            inserted_id = str(event.inserted_id)
            data["_id"] = inserted_id

            return data

        except Exception as e:
            print("ERROR")
            print(e)
            raise RuntimeError(
                "An error occurred while saving the event to the database."
            ) from e

    def get_event(self, event_id):
        resp = tools.JsonResp({"message": "Event not found!"}, 404)

        event = app.db.events.find_one({"_id": ObjectId(event_id)})
        if event:
            resp = tools.JsonResp(event, 200)

        return resp

    def get_events(
        self, stream_id, start_timestamp=None, end_timestamp=None, limit=None, page=None
    ):
        query = {}

        if stream_id:
            query["stream_id"] = stream_id

        if start_timestamp or end_timestamp:
            timestamp_filter = {}
            if start_timestamp:
                timestamp_filter["$gte"] = int(start_timestamp)
            if end_timestamp:
                timestamp_filter["$lte"] = int(end_timestamp)
            query["timestamp"] = timestamp_filter

        skip = (page) * limit

        try:
            cursor = (
                self.collection.find(query)
                .sort("timestamp", DESCENDING)
                .skip(skip)
                .limit(limit)
            )
            events = list(cursor)

            return tools.JsonResp({"message": "Success.", "data": events}, 200)
        except Exception as e:
            print(e)
            return tools.JsonResp(
                {"message": "Failed to fetch events from db.", "error": "db_error"}, 500
            )
