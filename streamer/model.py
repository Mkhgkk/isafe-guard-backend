from database.db import create_db_instance

db = create_db_instance()

class Streams:
    @staticmethod
    def get_all_streams():
        streams = db.streams.find()
        return streams