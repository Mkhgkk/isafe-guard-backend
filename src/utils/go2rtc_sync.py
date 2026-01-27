"""
Utility module for syncing database streams with go2rtc configuration.
"""
import os
import yaml
from pathlib import Path
from database import get_database
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)

# Environment flag to enable/disable go2rtc integration
USE_GO2RTC = os.environ.get("USE_GO2RTC", "false").lower() in ["true", "1", "yes"]

# Path to go2rtc.yaml - adjust based on your deployment setup
GO2RTC_CONFIG_PATH = os.environ.get(
    "GO2RTC_CONFIG_PATH",
    "/app/go2rtc.yaml"  # Default path in Docker container
)

def sync_streams_to_go2rtc():
    """
    Sync database stream IDs to go2rtc.yaml configuration file.
    This ensures all streams in the database are available in go2rtc.
    """
    # Check if go2rtc is enabled
    if not USE_GO2RTC:
        log_event(
            logger,
            "debug",
            "go2rtc sync skipped (USE_GO2RTC=false)",
            event_type="go2rtc_sync"
        )
        return {
            "status": "skipped",
            "message": "go2rtc integration is disabled"
        }

    try:
        # Get all streams from database
        db = get_database()
        streams_cursor = db.streams.find({}, {"stream_id": 1, "_id": 0})
        stream_ids = [stream["stream_id"] for stream in streams_cursor]

        if not stream_ids:
            log_event(
                logger,
                "info",
                "No streams found in database to sync with go2rtc",
                event_type="go2rtc_sync"
            )
            return {"status": "success", "message": "No streams to sync"}

        log_event(
            logger,
            "info",
            f"Found {len(stream_ids)} streams in database: {stream_ids}",
            event_type="go2rtc_sync"
        )

        # Read existing go2rtc.yaml configuration
        config_path = Path(GO2RTC_CONFIG_PATH)

        if not config_path.exists():
            log_event(
                logger,
                "warning",
                f"go2rtc config file not found at {config_path}",
                event_type="go2rtc_sync"
            )
            return {
                "status": "error",
                "message": f"Config file not found at {config_path}"
            }

        # Load existing config
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

        # Ensure streams section exists and is a dict (not None)
        if 'streams' not in config or config['streams'] is None:
            config['streams'] = {}

        # Track changes
        added_streams = []
        existing_streams = []

        # Add or update stream entries
        for stream_id in stream_ids:
            if stream_id not in config['streams']:
                # Add new stream with empty configuration
                config['streams'][stream_id] = ""
                added_streams.append(stream_id)
            else:
                existing_streams.append(stream_id)

        # Write updated config back to file
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        # Log results
        if added_streams:
            log_event(
                logger,
                "info",
                f"Added {len(added_streams)} new stream(s) to go2rtc: {added_streams}",
                event_type="go2rtc_sync"
            )

        if existing_streams:
            log_event(
                logger,
                "info",
                f"Found {len(existing_streams)} existing stream(s) in go2rtc: {existing_streams}",
                event_type="go2rtc_sync"
            )

        return {
            "status": "success",
            "message": f"Synced {len(stream_ids)} streams to go2rtc",
            "data": {
                "total_streams": len(stream_ids),
                "added": added_streams,
                "existing": existing_streams
            }
        }

    except FileNotFoundError as e:
        log_event(
            logger,
            "error",
            f"go2rtc config file not found: {e}",
            event_type="go2rtc_sync"
        )
        return {"status": "error", "message": f"Config file not found: {e}"}

    except yaml.YAMLError as e:
        log_event(
            logger,
            "error",
            f"Error parsing go2rtc YAML config: {e}",
            event_type="go2rtc_sync"
        )
        return {"status": "error", "message": f"YAML parsing error: {e}"}

    except Exception as e:
        log_event(
            logger,
            "error",
            f"Error syncing streams to go2rtc: {e}",
            event_type="go2rtc_sync"
        )
        return {"status": "error", "message": f"Sync error: {e}"}


def remove_stream_from_go2rtc(stream_id):
    """
    Remove a stream from go2rtc.yaml configuration.

    Args:
        stream_id: The ID of the stream to remove
    """
    # Check if go2rtc is enabled
    if not USE_GO2RTC:
        return {
            "status": "skipped",
            "message": "go2rtc integration is disabled"
        }

    try:
        config_path = Path(GO2RTC_CONFIG_PATH)

        if not config_path.exists():
            log_event(
                logger,
                "warning",
                f"go2rtc config file not found at {config_path}",
                event_type="go2rtc_sync"
            )
            return {"status": "error", "message": "Config file not found"}

        # Load existing config
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

        # Remove stream if it exists
        if 'streams' in config and config['streams'] is not None and stream_id in config['streams']:
            del config['streams'][stream_id]

            # Write updated config back to file
            with open(config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            log_event(
                logger,
                "info",
                f"Removed stream '{stream_id}' from go2rtc config",
                event_type="go2rtc_sync"
            )
            return {"status": "success", "message": f"Stream {stream_id} removed"}
        else:
            log_event(
                logger,
                "info",
                f"Stream '{stream_id}' not found in go2rtc config",
                event_type="go2rtc_sync"
            )
            return {"status": "success", "message": "Stream not found in config"}

    except Exception as e:
        log_event(
            logger,
            "error",
            f"Error removing stream from go2rtc: {e}",
            event_type="go2rtc_sync"
        )
        return {"status": "error", "message": f"Error: {e}"}
