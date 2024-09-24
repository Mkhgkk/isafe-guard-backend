from database.db import create_db_instance
from bson import ObjectId

db = create_db_instance()
streams = db.streams

def insert_stream(data):
    stream = {
        "url": "something something"
    }
    result = streams.insert_one(stream)
    return {"inserted_id": str(result.inserted_id)}

def get_streams():
    data = streams.find()
    return data