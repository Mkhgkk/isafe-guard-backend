from pymongo import MongoClient

MONGO_URI = "mongodb+srv://emmachalz:Hybridph4ntom@cluster0.d4no3.mongodb.net/mydatabase?retryWrites=true&w=majority&appName=Cluster0"
DATABASE_NAME = "isafe_guard"

client = None
db = None

def create_db_instance():
    
    global client, db
    if client is None:
        client = MongoClient(MONGO_URI)
        db = client[DATABASE_NAME]
        print(f"Connected to {DATABASE_NAME}!")
    return db

def close_db_connection():
    """
    Close the MongoDB client connection.
    """
    global client
    if client is not None:
        client.close()
        client = None
