from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)
from typing import Optional

from .base import ONVIFCameraBase


class CameraController(ONVIFCameraBase):
    """Camera controller for basic PTZ operations."""
    
    def __init__(self, ip: str, port: int, username: str, password: str, profile_name: Optional[str] = None) -> None:
        super().__init__(ip, port, username, password, profile_name)

    def move_camera(self, direction: str, speed: Optional[float] = None) -> None:
        """Move camera in specified direction or zoom continuously."""
        if direction in ["zoom_in", "zoom_out"]:
            # # Use absolute move for zoom
            # current_pan, current_tilt, _ = self.get_current_position()
            
            # try:
            #     self.absolute_move(current_pan, current_tilt, zoom_amount, zoom_speed=0.5)

            # Use continuous move for zoom
            try:
                continuous_move_request = self.ptz_service.create_type("ContinuousMove")
                continuous_move_request.ProfileToken = self.profile_token

                zoom_speed = 0.5 if speed is None else speed

                zoom_velocity = zoom_speed if direction == "zoom_in" else -zoom_speed

                continuous_move_request.Velocity = {
                    "PanTilt": {"x": 0.0, "y": 0.0},
                    "Zoom": {"x": zoom_velocity},
                }

                self.ptz_service.ContinuousMove(continuous_move_request)
                # log_event(logger, "info", f"Camera {direction} continuously.", event_type="info")
            except Exception as e:
                log_event(logger, "error", f"An error occurred during zoom: {e}", event_type="error")
        else:
            # Use continuous move for pan and tilt - this creates continuous movement
            # that needs to be manually stopped
            try:
                continuous_move_request = self.ptz_service.create_type("ContinuousMove")
                continuous_move_request.ProfileToken = self.profile_token

                continuous_move_request.Velocity = {
                    "PanTilt": {"x": 0.0, "y": 0.0},
                    "Zoom": {"x": 0.0},
                }

                # pan_speed = 0.8
                # tilt_speed = 0.8

                pan_speed = speed if speed is not None else 0.8
                tilt_speed = speed if speed is not None else 0.8

                if direction == "up":
                    continuous_move_request.Velocity["PanTilt"]["y"] = tilt_speed
                elif direction == "down":
                    continuous_move_request.Velocity["PanTilt"]["y"] = -tilt_speed
                elif direction == "left":
                    continuous_move_request.Velocity["PanTilt"]["x"] = -pan_speed
                elif direction == "right":
                    continuous_move_request.Velocity["PanTilt"]["x"] = pan_speed

                self.ptz_service.ContinuousMove(continuous_move_request)
                # log_event(logger, "info", f"Camera moving {direction} continuously.", event_type="info")
            except Exception as e:
                log_event(logger, "error", f"An error occurred during movement: {e}", event_type="error")

    def stop_camera(self) -> None:
        """Stop the camera movement."""
        try:
            self.stop_movement()
            log_event(logger, "info", "Camera movement stopped.", event_type="info")
        except Exception as e:
            log_event(logger, "error", f"An error occurred while stopping: {e}", event_type="error")