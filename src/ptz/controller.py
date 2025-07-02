import logging
from typing import Optional

from .base import ONVIFCameraBase


class CameraController(ONVIFCameraBase):
    """Camera controller for basic PTZ operations."""
    
    def __init__(self, ip: str, port: int, username: str, password: str) -> None:
        super().__init__(ip, port, username, password)

    def move_camera(self, direction: str, zoom_amount: Optional[float] = None) -> None:
        """Move camera in specified direction or zoom to specified level."""
        if direction in ["zoom_in", "zoom_out"] and zoom_amount is not None:
            # Use absolute move for zoom
            current_pan, current_tilt, _ = self.get_current_position()
            
            try:
                self.absolute_move(current_pan, current_tilt, zoom_amount, zoom_speed=0.5)
                # logging.info(f"Camera zoomed to level {zoom_amount}.")
            except Exception as e:
                logging.error(f"An error occurred during zoom: {e}")
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

                pan_speed = 0.8
                tilt_speed = 0.8

                if direction == "up":
                    continuous_move_request.Velocity["PanTilt"]["y"] = tilt_speed
                elif direction == "down":
                    continuous_move_request.Velocity["PanTilt"]["y"] = -tilt_speed
                elif direction == "left":
                    continuous_move_request.Velocity["PanTilt"]["x"] = -pan_speed
                elif direction == "right":
                    continuous_move_request.Velocity["PanTilt"]["x"] = pan_speed

                self.ptz_service.ContinuousMove(continuous_move_request)
                # logging.info(f"Camera moving {direction} continuously.")
            except Exception as e:
                logging.error(f"An error occurred during movement: {e}")

    def stop_camera(self) -> None:
        """Stop the camera movement."""
        try:
            self.stop_movement()
            logging.info("Camera movement stopped.")
        except Exception as e:
            logging.error(f"An error occurred while stopping: {e}")