"""Service for managing hazard zones and safe areas for streams."""

import cv2
import os
import traceback
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional, Dict, List, Any

from database import get_database
from flask import current_app as app
from marshmallow import ValidationError

from main.shared import streams, safe_area_trackers
from main.stream.validation import SafeAreaSchema
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


class HazardService:
    """Service for managing hazard zone and safe area configurations."""

    @staticmethod
    def save_safe_area(
        stream_id: str,
        coords: List[List[float]],
        static_mode: bool = True,
        reference_image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save safe area configuration to database and update active stream.

        Args:
            stream_id: Stream identifier
            coords: List of coordinate pairs defining the safe area polygon
            static_mode: Whether to use static or dynamic detection mode
            reference_image: Optional reference image URL

        Returns:
            dict: Result with status, message, and data
        """
        try:
            db = get_database()

            # Create safe area data structure
            safe_area_data = {
                "coords": coords,
                "static_mode": static_mode,
                "reference_image": reference_image,
                "updated_at": datetime.now(timezone.utc),
            }

            # If no existing safe area, add created_at
            existing_stream = db.streams.find_one({"stream_id": stream_id})
            if not existing_stream:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            if not existing_stream.get("safe_area"):
                safe_area_data["created_at"] = datetime.now(timezone.utc)

            # Validate safe area structure
            safe_area_schema = SafeAreaSchema()

            try:
                validated_safe_area = safe_area_schema.load(safe_area_data)
            except ValidationError as e:
                return {
                    "status": "error",
                    "message": "Invalid safe area data",
                    "errors": e.messages,
                }

            # Update safe area in database
            result = db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"safe_area": validated_safe_area}}
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update the SafeAreaTracker for active stream
            if stream_id in safe_area_trackers:
                safe_area_tracker = safe_area_trackers[stream_id]
                safe_area_tracker.set_static_mode(static_mode)
                log_event(
                    logger,
                    "info",
                    f"Updated SafeAreaTracker static mode for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Safe area saved successfully for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Safe area saved successfully",
                "data": {"stream_id": stream_id, "safe_area": validated_safe_area},
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger, "error", f"Error saving safe area: {e}", event_type="error"
            )
            return {
                "status": "error",
                "message": f"Failed to save safe area: {str(e)}",
            }

    @staticmethod
    def get_safe_area(stream_id: str) -> Dict[str, Any]:
        """Get saved safe area configuration from database.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and safe area data
        """
        try:
            db = get_database()

            # Get stream from database
            stream = db.streams.find_one({"stream_id": stream_id})
            if not stream:
                raise ValueError(f"Stream with ID '{stream_id}' not found.")

            # Get safe area from stream data
            safe_area = stream.get("safe_area")

            if safe_area is None:
                return {
                    "status": "success",
                    "message": "No safe area configured for this stream",
                    "data": None,
                }

            return {
                "status": "success",
                "message": "Safe area retrieved successfully",
                "data": {
                    "stream_id": stream_id,
                    "safe_area": safe_area,
                },
            }

        except ValueError as e:
            return {
                "status": "error",
                "message": str(e),
            }
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving safe area: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to retrieve safe area: {str(e)}",
            }

    @staticmethod
    def set_danger_zone(
        stream_id: str,
        coords: List[List[float]],
        image: str,
        static_mode: bool = True
    ) -> Dict[str, Any]:
        """Configure safe/danger zone for intrusion detection.

        Args:
            stream_id: Stream identifier
            coords: List of coordinate pairs defining the danger zone polygon
            image: Reference image URL
            static_mode: Whether to use static or dynamic detection mode

        Returns:
            dict: Result with status and message
        """
        REFERENCE_FRAME_DIR = "../static/frame_refs"

        try:
            # Validate required fields
            if not image or not coords or not stream_id:
                missing_fields = []
                if not stream_id:
                    missing_fields.append("streamId")
                if not image:
                    missing_fields.append("image")
                if not coords:
                    missing_fields.append("coords")

                return {
                    "status": "error",
                    "message": f"Missing required fields: {', '.join(missing_fields)}",
                }

            # Parse the image path
            parsed_url = urlparse(image)
            file_name = os.path.basename(parsed_url.path)

            image_path = os.path.join(
                os.path.dirname(__file__), "..", "..", REFERENCE_FRAME_DIR, file_name
            )
            image_path = os.path.abspath(image_path)

            # Load reference frame using OpenCV
            reference_frame = cv2.imread(image_path)
            if reference_frame is None:
                return {
                    "status": "error",
                    "message": f"Failed to load reference frame from {image_path}",
                }

            # Get the stream's SafeAreaTracker
            if stream_id not in safe_area_trackers:
                return {
                    "status": "error",
                    "message": f"SafeAreaTracker not found for stream: {stream_id}. Stream may not be active.",
                }

            safe_area_tracker = safe_area_trackers[stream_id]

            # Set the danger zone with the reference frame
            safe_area_tracker.set_safe_area(coords, reference_frame, static_mode)

            # Also save to database using save_safe_area
            result = HazardService.save_safe_area(
                stream_id=stream_id,
                coords=coords,
                static_mode=static_mode,
                reference_image=image
            )

            if result["status"] == "error":
                return result

            log_event(
                logger,
                "info",
                f"Danger zone set successfully for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": "Danger zone configured successfully",
            }

        except Exception as e:
            logger.error(f"Error setting danger zone for stream {stream_id}: {e}")
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
            }

    @staticmethod
    def set_camera_mode(stream_id: str, static_mode: bool) -> Dict[str, Any]:
        """Set camera mode for hazard area tracking.

        Args:
            stream_id: Stream identifier
            static_mode: True for static mode, False for dynamic mode

        Returns:
            dict: Result with status and message
        """
        try:
            # Get the stream's SafeAreaTracker
            if stream_id not in safe_area_trackers:
                return {
                    "status": "error",
                    "message": f"SafeAreaTracker not found for stream: {stream_id}. Stream may not be active.",
                }

            safe_area_tracker = safe_area_trackers[stream_id]
            safe_area_tracker.set_static_mode(static_mode)

            # Update database
            db = get_database()
            result = db.streams.update_one(
                {"stream_id": stream_id},
                {"$set": {"safe_area.static_mode": static_mode}},
            )

            mode_name = "static" if static_mode else "dynamic"

            if result.modified_count > 0:
                log_event(
                    logger,
                    "info",
                    f"Camera mode set to {mode_name} for stream: {stream_id}",
                    event_type="info",
                )
                return {
                    "status": "success",
                    "message": f"Camera mode set to {mode_name} successfully",
                }
            else:
                return {
                    "status": "success",
                    "message": f"Camera mode already set to {mode_name}",
                }

        except Exception as e:
            logger.error(f"Error setting camera mode for stream {stream_id}: {e}")
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
            }

    @staticmethod
    def get_camera_mode(stream_id: str) -> Dict[str, Any]:
        """Get current camera mode for hazard area tracking.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and camera mode data
        """
        try:
            db = get_database()

            # Get stream from database
            stream = db.streams.find_one({"stream_id": stream_id})
            if not stream:
                return {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found.",
                }

            # Get safe area and its static_mode
            safe_area = stream.get("safe_area", {})
            static_mode = safe_area.get("static_mode", True)  # Default to True

            mode_name = "static" if static_mode else "dynamic"

            return {
                "status": "success",
                "message": "Camera mode retrieved successfully",
                "data": {
                    "stream_id": stream_id,
                    "static_mode": static_mode,
                    "mode_name": mode_name,
                },
            }

        except Exception as e:
            logger.error(f"Error getting camera mode for stream {stream_id}: {e}")
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
            }

    @staticmethod
    def toggle_intrusion_detection(stream_id: str) -> Dict[str, Any]:
        """Toggle intrusion detection for a stream.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and new intrusion_detection state
        """
        try:
            db = get_database()

            # Get stream from database
            stream_doc = db.streams.find_one({"stream_id": stream_id})
            if not stream_doc:
                return {
                    "status": "error",
                    "message": f"Stream with ID '{stream_id}' not found.",
                }

            # Toggle intrusion_detection
            current_status = stream_doc.get("intrusion_detection", False)
            new_status = not current_status

            # Update database
            result = db.streams.update_one(
                {"stream_id": stream_id},
                {
                    "$set": {
                        "intrusion_detection": new_status,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            if result.modified_count == 0:
                log_event(
                    logger,
                    "warning",
                    f"No document was modified for stream_id: {stream_id}",
                    event_type="warning",
                )

            # Update active stream if it exists
            if stream_id in streams:
                video_streaming = streams[stream_id]
                video_streaming.set_intrusion_detection(new_status)

                log_event(
                    logger,
                    "info",
                    f"Intrusion detection {'enabled' if new_status else 'disabled'} for active stream: {stream_id}",
                    event_type="info",
                )

            log_event(
                logger,
                "info",
                f"Intrusion detection toggled to {new_status} for stream: {stream_id}",
                event_type="info",
            )

            return {
                "status": "success",
                "message": f"Intrusion detection {'enabled' if new_status else 'disabled'} successfully",
                "data": {
                    "stream_id": stream_id,
                    "intrusion_detection": new_status,
                },
            }

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error toggling intrusion detection: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to toggle intrusion detection: {str(e)}",
            }
