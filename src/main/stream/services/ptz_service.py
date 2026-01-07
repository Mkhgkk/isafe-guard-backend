"""Service for managing PTZ camera controls."""

from typing import Dict, Any

from main.shared import streams
from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)


class PTZService:
    """Service for managing PTZ camera controls."""

    @staticmethod
    def get_current_ptz_values(stream_id: str) -> Dict[str, Any]:
        """Get current PTZ (Pan-Tilt-Zoom) values.

        Args:
            stream_id: Stream identifier

        Returns:
            dict: Result with status, message, and data (x, y, z)
        """
        stream = streams.get(stream_id)
        if stream is None:
            return {
                "status": "error",
                "message": f"Stream with ID '{stream_id}' not found or is not active.",
                "error_code": "not_found",
            }

        camera_controller = stream.camera_controller

        if camera_controller is None:
            return {
                "status": "error",
                "message": f"Camera controller not available for stream '{stream_id}'. PTZ control might not be enabled.",
            }

        try:
            pan, tilt, zoom = camera_controller.get_current_position()
            return {
                "status": "success",
                "message": "ok",
                "data": {"x": pan, "y": tilt, "z": zoom},
            }
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error retrieving PTZ position for stream_id '{stream_id}': {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to get PTZ position: {str(e)}",
            }

    @staticmethod
    def ptz_controls(stream_id: str, command: str, speed: float) -> Dict[str, Any]:
        """Control PTZ camera movements.

        Args:
            stream_id: Stream identifier
            command: PTZ command (up, down, left, right, zoom_in, zoom_out, stop, home)
            speed: Movement speed

        Returns:
            dict: Result with status and message
        """
        stream = streams.get(stream_id)
        if stream is None:
            return {
                "status": "error",
                "message": f"Stream '{stream_id}' not found or not active",
                "error_code": "not_found",
            }

        camera_controller = stream.camera_controller
        if camera_controller is None:
            return {
                "status": "error",
                "message": f"PTZ not available for stream '{stream_id}'",
                "error_code": "not_found",
            }

        command_map = {
            "up": lambda: camera_controller.move_continuous(0, speed, 0),
            "down": lambda: camera_controller.move_continuous(0, -speed, 0),
            "left": lambda: camera_controller.move_continuous(-speed, 0, 0),
            "right": lambda: camera_controller.move_continuous(speed, 0, 0),
            "zoom_in": lambda: camera_controller.move_continuous(0, 0, speed),
            "zoom_out": lambda: camera_controller.move_continuous(0, 0, -speed),
            "stop": lambda: camera_controller.stop(),
            "home": lambda: camera_controller.go_to_home_position(),
        }

        if command in command_map:
            command_map[command]()
            return {"status": "success", "message": f"PTZ command '{command}' executed"}
        else:
            return {"status": "error", "message": f"Unknown command '{command}'"}
