from marshmallow import Schema, fields, ValidationError, validate
import json
from flask import current_app as app
from flask import request

from main import tools

from bson import ObjectId

class EventSchema(Schema):
    stream_id = fields.String(required=True)
    title = fields.String(required=True)
    description = fields.String(required=True)
    timestamp = fields.Integer(required=True)
    thumbnail = fields.String(required=True)
    video_filename = fields.String(required=True)

event_schema = EventSchema()

class Event:

    def create_event(self, data):
        errors = event_schema.validate(data)
        if errors:
            raise ValidationError(errors)
        
        try:
            event = app.db.events.insert_one(data)
            inserted_id = str(event.inserted_id)
            data["_id"] = inserted_id

            return data
        
        except Exception as e: 
              raise RuntimeError("An error occurred while saving the event to the database.") from e
        
    def get(self, event_id):
        resp = tools.JsonResp({ "message": "Event(s) not found!"}, 404)

        if event_id:
            event = app.db.events.find_one({ "_id": ObjectId(event_id) })
            if event:
                resp = tools.JsonResp(event, 200)
        
        
        else:
            events = list(app.db.streams.find())
            if events:
                resp = tools.JsonResp(events, 200)

        return resp

