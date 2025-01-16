import time
import logging
import requests
from typing import List
from config import WATCH_NOTIFICATION_URL

def send_watch_notification(reasons: List[str] = ["Wear helmet"]) -> None:
        data = {
            "phone_id": "4b91e2ca33c3119c",
            "status": "UnSafe",
            # "detail": ["안전모 미착용"],
            # "detail": [reasons] if len(reasons ==1) else reasons,
            "detail": reasons,
            "timestamp": str(time.time_ns())
        }
        url = WATCH_NOTIFICATION_URL

        try:
            response = requests.post(url, json=data)
            if response.status_code in (200, 201):
                logging.info("Notification sent successfully!")
            else:
                logging.warning(f"Failed to send notification. Status code: {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"Error occurred: {e}")