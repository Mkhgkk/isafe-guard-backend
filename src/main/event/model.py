import os
import cv2
import json
import time
from utils.logging_config import get_logger, log_event
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
from utils.notifications import send_email_notification
from events import emit_event, EventType

logger = get_logger(__name__)


class EventSchema(Schema):
    stream_id = fields.String(required=True)
    reasons = fields.List(fields.String(), required=True)
    model_name = fields.String(required=True)
    timestamp = fields.Integer(required=True)
    thumbnail = fields.String(required=True)
    video_filename = fields.String(required=True)
    _id = fields.String(required=False)
    # event_type = fields.String(required=True, validate=validate.OneOf(['PPE', 'Ladder', 'Mobile Scaffolding', 'Cutting Welding']))


event_schema = EventSchema()


class Event:
    def __init__(self):
        self.collection = get_database()["events"]

    def _notify_stream_event_status(self, stream_ids):
        """Notify frontend about event status changes for streams via WebSocket"""
        try:
            # Get unresolved event counts for affected streams
            pipeline = [
                {
                    "$match": {
                        "stream_id": {"$in": stream_ids},
                        "is_resolved": {"$ne": True},
                    }
                },
                {"$group": {"_id": "$stream_id", "unresolved_count": {"$sum": 1}}},
            ]
            event_counts = list(self.collection.aggregate(pipeline))
            count_dict = {
                item["_id"]: item["unresolved_count"] for item in event_counts
            }

            # Emit status for each affected stream
            for stream_id in stream_ids:
                unresolved_count = count_dict.get(stream_id, 0)
                data = {
                    "stream_id": stream_id,
                    "unresolved_events": unresolved_count,
                    "has_unresolved": unresolved_count > 0,
                }

                emit_event(
                    event_type=EventType.STREAM_EVENT_STATUS,
                    data=data,
                    # custom_event_name="stream_event_status",
                    room="monitoring",  # Main monitoring page room
                    broadcast=True,
                )

            log_event(
                logger,
                "info",
                f"Notified stream event status for streams: {stream_ids}",
                event_type="info",
            )

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error notifying stream event status: {e}",
                event_type="error",
            )

    @staticmethod
    def save(
        stream_id: str,
        frame: np.ndarray,
        reasons: List[str],
        model_name: str,
        start_time: float,
        filename: str,
        _id: ObjectId,
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
            log_event(
                logger, "error", "Failed to save thumbnail image.", event_type="error"
            )
            return

        try:
            data = {
                "stream_id": stream_id,
                "reasons": reasons,
                "model_name": model_name,
                "timestamp": int(start_time),
                "thumbnail": image_filename,
                "video_filename": filename,
                "_id": _id,
            }

            response = Event().create_event(data)
            log_event(
                logger,
                "info",
                f"Event saved successfully: {response}",
                event_type="info",
            )
            # send_email_notification(reasons, response["_id"], stream_id)
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error saving event to database: {e}",
                event_type="error",
            )

    def create_event(self, data):
        # errors = event_schema.validate(data)
        # if errors:
        #     raise ValidationError(errors)

        try:
            event = self.collection.insert_one(data)
            inserted_id = str(event.inserted_id)
            data["_id"] = inserted_id

            print("CREATED_ID: ", data["_id"])
            print("INSERTED_ID: ", inserted_id)

            # Notify about new event for the stream (increases unresolved count)
            stream_id = data.get("stream_id")
            if stream_id:
                self._notify_stream_event_status([stream_id])

            return data

        except Exception as e:
            log_event(logger, "error", "An error occured: ", e, event_type="error")
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
        self,
        stream_id,
        start_timestamp=None,
        end_timestamp=None,
        is_resolved=None,
        limit=None,
        page=None,
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

        if is_resolved is not None:
            if is_resolved.lower() == "true":
                query["is_resolved"] = True
            elif is_resolved.lower() == "false":
                query["is_resolved"] = {"$ne": True}

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
            log_event(logger, "error", "An error occured: ", e, event_type="error")
            return tools.JsonResp(
                {"message": "Failed to fetch events from db.", "error": "db_error"}, 500
            )

    def bulk_resolve_events(self, event_ids):
        try:
            object_ids = [ObjectId(event_id) for event_id in event_ids]

            # Get stream_ids for the events being resolved
            affected_events = list(
                self.collection.find({"_id": {"$in": object_ids}}, {"stream_id": 1})
            )
            affected_stream_ids = list(
                set(event["stream_id"] for event in affected_events)
            )

            # Update the events
            result = self.collection.update_many(
                {"_id": {"$in": object_ids}}, {"$set": {"is_resolved": True}}
            )

            # Notify about stream event status changes
            if result.modified_count > 0 and affected_stream_ids:
                self._notify_stream_event_status(affected_stream_ids)

            return tools.JsonResp(
                {
                    "message": "Events resolved successfully.",
                    "modified_count": result.modified_count,
                },
                200,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error resolving events: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"message": "Failed to resolve events.", "error": str(e)}, 500
            )

    def bulk_delete_events(self, event_ids):
        try:
            object_ids = [ObjectId(event_id) for event_id in event_ids]

            # Get stream_ids for the events being deleted (before deletion)
            affected_events = list(
                self.collection.find({"_id": {"$in": object_ids}}, {"stream_id": 1})
            )
            affected_stream_ids = list(
                set(event["stream_id"] for event in affected_events)
            )

            # First check if all events are resolved
            unresolved_count = self.collection.count_documents(
                {"_id": {"$in": object_ids}, "is_resolved": {"$ne": True}}
            )

            if unresolved_count > 0:
                return tools.JsonResp(
                    {
                        "message": "Cannot delete unresolved events. Only resolved events can be deleted.",
                        "unresolved_count": unresolved_count,
                    },
                    400,
                )

            # Delete only resolved events
            result = self.collection.delete_many(
                {"_id": {"$in": object_ids}, "is_resolved": True}
            )

            # Notify about stream event status changes (counts will be updated)
            if result.deleted_count > 0 and affected_stream_ids:
                self._notify_stream_event_status(affected_stream_ids)

            return tools.JsonResp(
                {
                    "message": "Events deleted successfully.",
                    "deleted_count": result.deleted_count,
                },
                200,
            )
        except Exception as e:
            log_event(
                logger, "error", f"Error deleting events: {e}", event_type="error"
            )
            return tools.JsonResp(
                {"message": "Failed to delete events.", "error": str(e)}, 500
            )
