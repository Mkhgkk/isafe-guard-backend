import os
from utils.logging_config import get_logger, log_event
import subprocess
from typing import Optional

logger = get_logger(__name__)


def du(path: str) -> str:
    return subprocess.check_output(["du", "-sh", path]).split()[0].decode("utf-8")


def df() -> Optional[str]:
    try:
        result = subprocess.check_output(
            "df -h | awk '$NF==\"/\" {print $2, $3, $4}'", shell=True, text=True
        )
        return result.strip()
    except subprocess.CalledProcessError as e:
        log_event(logger, "error", f"Error: {e}", event_type="error")
        return None


