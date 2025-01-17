from typing import Tuple, Optional
from onvif import ONVIFCamera
import logging


class CameraController:
    def __init__(self, ip: str, port: int, username: str, password: str) -> None:
        self.camera = ONVIFCamera(ip, port, username, password)
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()
        if self.profiles is None:
            raise ValueError(
                "No profiles returned from the camera. Please check connection or credentials."
            )
        self.profile_token = self.profiles[0].token

    def get_zoom_level(self) -> float:
        try:
            # status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            if not status:
                raise ValueError(
                    "GetStatus() returned None. Check camera connectivity and credentials."
                )
            if not hasattr(status, "Position"):
                raise ValueError(
                    "Status object does not contain a 'Position' attribute."
                )
            current_zoom = status.Position.Zoom.x
            return float(current_zoom)
        except Exception as e:
            logging.error(f"An error occurred while getting zoom level: {e}")
            return 0.0

    def get_current_position(self) -> Tuple[float, float, float]:
        try:
            # status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            if not status:
                raise ValueError(
                    "GetStatus() returned None. Check camera connectivity and credentials."
                )
            if not hasattr(status, "Position"):
                raise ValueError(
                    "Status object does not contain a 'Position' attribute."
                )
            current_pan = status.Position.PanTilt.x
            current_tilt = status.Position.PanTilt.y
            current_zoom = status.Position.Zoom.x
            return float(current_pan), float(current_tilt), float(current_zoom)
        except Exception as e:
            logging.error(f"An error occurred while getting current position: {e}")
            return 0.0, 0.0, 0.0

    def move_camera(self, direction: str, zoom_amount: Optional[float] = None) -> None:
        if direction in ["zoom_in", "zoom_out"] and zoom_amount is not None:
            # use AbsoluteMove for zoom
            absolute_move_request = self.ptz_service.create_type("AbsoluteMove")
            absolute_move_request.ProfileToken = self.profile_token

            current_pan, current_tilt, current_zoom = self.get_current_position()

            # define the absolute position, keeping current Pan and Tilt, and setting new Zoom
            absolute_move_request.Position = {
                "PanTilt": {"x": current_pan, "y": current_tilt},
                "Zoom": {"x": zoom_amount},
            }
            absolute_move_request.Speed = {"Zoom": {"x": 0.5}}

            try:
                self.ptz_service.AbsoluteMove(absolute_move_request)
                # logging.info(f"Camera zoomed to level {zoom_amount}.")
            except Exception as e:
                logging.error(f"An error occurred during zoom: {e}")
        else:
            # use ContinuousMove for pan and tilt
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

            try:
                self.ptz_service.ContinuousMove(continuous_move_request)
                # logging.info(f"Camera moving {direction} continuously.")
            except Exception as e:
                logging.error(f"An error occurred during movement: {e}")

    def stop_camera(self) -> None:
        """Function to stop the camera movement."""
        stop_request = self.ptz_service.create_type("Stop")
        stop_request.ProfileToken = self.profile_token
        stop_request.PanTilt = True
        stop_request.Zoom = True

        try:
            self.ptz_service.Stop(stop_request)
            logging.info("Camera movement stopped.")
        except Exception as e:
            logging.error(f"An error occurred while stopping: {e}")
