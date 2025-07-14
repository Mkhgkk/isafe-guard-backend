import os
import time
import smtplib
import requests
from typing import List
from bson import ObjectId
from config import WATCH_NOTIFICATION_URL, RECEIVER_EMAILS, SENDER_EMAIL, EMAIL_PASSWORD
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


def send_watch_notification(reasons: List[str] = ["Wear helmet"]) -> None:
    data = {
        "phone_id": "4b91e2ca33c3119c",
        "status": "UnSafe",
        # "detail": ["안전모 미착용"],
        # "detail": [reasons] if len(reasons ==1) else reasons,
        "detail": reasons,
        "timestamp": str(time.time_ns()),
    }
    url = WATCH_NOTIFICATION_URL

    try:
        response = requests.post(url, json=data)
        if response.status_code in (200, 201):
            log_event(logger, "info", "Notification sent successfully!", event_type="info")
        else:
            log_event(logger, "warning",
                f"Failed to send notification. Status code: {response.status_code}",
                event_type="notification_failed"
            )
    except requests.RequestException as e:
        log_event(logger, "error", f"Error occurred: {e}", event_type="error")


def send_email_notification(
    reasons: List[str], event_id: ObjectId, stream_id: str
) -> None:
    PROTOCOL = os.getenv("PROTOCOL", "http")
    DOMAIN = os.getenv("DOMAIN", "isafe.re.kr")

    if not RECEIVER_EMAILS or len(RECEIVER_EMAILS) == 0:
        return

    sender_email = SENDER_EMAIL
    receiver_emails = RECEIVER_EMAILS
    password = EMAIL_PASSWORD

    subject = "Unsafe Event Notification"
    body = f"Unsafe event occured. You can review the event in the link below:\n{PROTOCOL}://{DOMAIN}/events/{str(event_id)}."

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_emails)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_emails, message.as_string())
            log_event(logger, "info", "Email sent successfully!", event_type="info")
    except Exception as e:
        log_event(logger, "error", f"Failed to send email: {e}", event_type="error")
