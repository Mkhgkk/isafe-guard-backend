import cv2
import numpy as np
from typing import List, Tuple, Dict, Any
from detection.kdl_detector import get_kdl_client
from events.api import emit_dynamic_event
from events.events import EventType
from utils.logging_config import get_logger
from detection import draw_text_with_background

logger = get_logger(__name__)

# Global cache for KDL metadata per stream_id
kdl_metadata_cache: Dict[str, Dict[str, Any]] = {}


def detect_kdl(
    image: np.ndarray,
    _results: List[Any],
    stream_id: str = "default",
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:
    """KDL detection - sends frame to KDL server via WebSocket.

    This function sends the frame to the KDL server asynchronously.
    Results will be received later via WebSocket callback and emitted to frontend.
    It also draws cached metadata on the current frame.

    Args:
        image: Input image array
        _results: Not used for KDL (detection happens on server)
        stream_id: Stream identifier for tracking

    Returns:
        Tuple containing:
        - final_status: Always "Safe" (actual status comes via WebSocket callback)
        - reasons: Empty list (actual reasons come via WebSocket callback)
        - bboxes: Empty list (actual bboxes come via WebSocket callback)
    """
    # logger.info(f"detect_kdl called with stream_id: {stream_id}")

    # Get the global KDL client
    kdl_client = get_kdl_client()

    if kdl_client is None:
        logger.warning("KDL client not initialized")
        return "Safe", [], []

    # Draw cached metadata on the current frame if available
    if stream_id in kdl_metadata_cache:
        cached_data = kdl_metadata_cache[stream_id]
        gauge_xyxy = cached_data.get("gauge_xyxy", [])
        pin_angle = cached_data.get("pin_angle", [])
        gauge_status = cached_data.get("gauge_status", "normal")

        # Draw box around gauge if gauge_xyxy is available
        if gauge_xyxy and len(gauge_xyxy) == 4:
            x1, y1, x2, y2 = map(int, gauge_xyxy)

            # Determine box color based on gauge status
            if gauge_status == "danger":
                box_color = (0, 0, 255)  # Red
            elif gauge_status == "warning":
                box_color = (0, 165, 255)  # Orange
            else:
                box_color = (0, 255, 0)  # Green

            # Draw rectangle around gauge
            cv2.rectangle(image, (x1, y1), (x2, y2), box_color, 2)

            # Draw angle text if available
            if pin_angle and len(pin_angle) > 0:
                angle_value = pin_angle[0]
                angle_text = f"Angle: {angle_value:.1f}°"

                # Position text above the gauge box
                text_position = (x1, max(y1 - 10, 25))

                # Determine background color based on gauge status
                if gauge_status == "danger":
                    bg_color = (0, 0, 255)  # Red
                elif gauge_status == "warning":
                    bg_color = (0, 165, 255)  # Orange
                else:
                    bg_color = (0, 255, 0)  # Green

                # Draw angle text with background
                draw_text_with_background(image, angle_text, text_position, bg_color, t_type="label")

    # Send frame to KDL server (non-blocking)
    kdl_client.send_frame(image, stream_id)

    # Return default safe status since actual results come asynchronously
    # The actual detection results will be emitted to frontend via WebSocket callback
    return "Safe", [], []


def handle_kdl_result(metadata: Dict[str, Any], image_bytes: bytes, stream_id: str):
    """Handle KDL detection results received from WebSocket.

    This function is called when results are received from the KDL server.
    It processes the results and emits them to the frontend.

    KDL Metadata format:
        {
            'timestamp': '2025-11-28 16:49:48',
            'gauge_status': 'normal | warning | danger',
            'gauge_xyxy': [x1, y1, x2, y2],
            'pin_angle': [angle_value],
            'comment': ''
        }

    Args:
        metadata: Detection metadata from KDL server
        image_bytes: Processed image bytes from KDL server
        stream_id: Stream identifier
    """
    # logger.info(f"KDL result received! Metadata: {metadata}, Image bytes size: {len(image_bytes)}")
    try:
        # Decode the image
        nparr = np.frombuffer(image_bytes, np.uint8)
        processed_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if processed_image is None:
            logger.error("Failed to decode KDL result image")
            return

        # Extract KDL-specific detection information from metadata
        gauge_status = metadata.get("gauge_status", "normal")
        gauge_xyxy = metadata.get("gauge_xyxy", [])
        pin_angle = metadata.get("pin_angle", [])
        timestamp = metadata.get("timestamp", "")
        comment = metadata.get("comment", "")

        # Cache the metadata for this stream_id
        kdl_metadata_cache[stream_id] = {
            "gauge_status": gauge_status,
            "gauge_xyxy": gauge_xyxy,
            "pin_angle": pin_angle,
            "timestamp": timestamp,
            "comment": comment,
        }

        # Emit the complete KDL detection results to frontend
        # Broadcast to all clients since KDL server doesn't track stream_id
        # logger.info(f"Broadcasting KDL_DETECTION event with identifier: {stream_id}")
        emit_dynamic_event(
            base_event_type=EventType.KDL_DETECTION,
            identifier=stream_id,
            data={
                "timestamp": timestamp,
                "gauge_status": gauge_status,
                "gauge_xyxy": gauge_xyxy,
                "pin_angle": pin_angle,
                "comment": comment,
            },
            room=None,
            broadcast=True,
        )
        # logger.info(f"KDL_DETECTION event broadcasted successfully")

        # If gauge status is warning or danger, emit an alert
        # Broadcast to all clients since KDL server doesn't track stream_id
        if gauge_status in ["warning", "danger"]:
            emit_dynamic_event(
                base_event_type=EventType.ALERT,
                identifier=stream_id,
                data={
                    "type": "kdl_detection",
                    "gauge_status": gauge_status,
                    "gauge_xyxy": gauge_xyxy,
                    "pin_angle": pin_angle,
                    "timestamp": timestamp,
                },
                room=None,
                broadcast=True,
            )

        # logger.debug(
        #     f"KDL detection result processed for stream {stream_id}: "
        #     f"gauge_status={gauge_status}, pin_angle={pin_angle}"
        # )

    except Exception as e:
        logger.error(f"Error handling KDL result: {e}")
