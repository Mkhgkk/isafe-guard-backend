from flask import current_app as app
from flask import Flask, request
from passlib.hash import pbkdf2_sha256
from jose import jwt
from main import tools
from main import auth
import json
import traceback
from datetime import datetime, timedelta

from utils import df, du
from config import STATIC_DIR, MODELS_DIR, BASE_DIR


class System:
    _instance = None  

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(System, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"): 
            self.disk_available = None
            self.disk_used = None
            self.disk_free = None

            self.disk_media = None
            self.disk_models = None
            self.base = None

            self.last_disk_check = None
            self.initialized = True

    def get_disk(self):
        try:
            if self.last_disk_check and datetime.now() - self.last_disk_check < timedelta(minutes=5):
                return tools.JsonResp({
                    "disk_available": self.disk_available,
                    "disk_used": self.disk_used,
                    "disk_free": self.disk_free,
                    "disk_media": self.disk_media,
                    "disk_models": self.disk_models,
                    "base": self.base,
                }, 200)

            total, used, free = df().split()
            media = du(STATIC_DIR)
            models = du(MODELS_DIR)
            base = du(BASE_DIR)

            self.last_disk_check = datetime.now()

            self.disk_available = total
            self.disk_used = used
            self.disk_free = free
            self.disk_media = media
            self.disk_models = models
            self.base = base

            return tools.JsonResp({
                "disk_available": total,
                "disk_used": used,
                "disk_free": free,
                "disk_media": media,
                "disk_models": models,
                "base": base
            }, 200)
        except Exception as e:
            print(f"Error: {e}")
            return tools.JsonResp({"data": str(e)}, 401)
