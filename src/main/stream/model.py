# from database.db import create_db_instance

# db = create_db_instance()
from flask import current_app as app

class Stream:
    @staticmethod
    def get_all_streams():
        streams = app.db.streams.find()
        return streams