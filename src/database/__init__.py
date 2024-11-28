from appwrite.client import Client
from appwrite.services.databases import Databases

_databases = None

def initialize_appwrite_client():
    """
    Initialize the Appwrite client and return the Databases instance.
    Raises an exception if initialization fails.
    """
    try:
        client = Client()
        client.set_endpoint('http://172.105.209.31/v1')\
            .set_project('66f4c2e6001ef89c0f5c')\
            .set_key('standard_a5d6a12567fad8968cf5e2bc4482006c886d22e175e2d9bdabfea4453958462e507effc6276fc3f9b6f766bf34bf5290a9cb56d8277003a4128de039fd5a5d7299c12ea831eccc96d04c50655e5f0a7df0a5fcd80532a664649f0fb9e34cdfe33f12d91035738668f6b2bbefb7ed665c8905eb0796038981498cd4e7a9bc22aa')
        return Databases(client)
    except Exception as e:
        raise ConnectionError(f"Failed to initialize Appwrite client: {e}")

def get_database_instance():
    """
    Get the singleton Databases instance. Initialize it if it does not exist.
    """
    global _databases
    if _databases is None:
        _databases = initialize_appwrite_client()
    return _databases