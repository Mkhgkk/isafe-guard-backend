from utils.logging_config import get_logger, log_event

logger = get_logger(__name__)
from typing import Tuple, Optional
from onvif import ONVIFCamera # pyright: ignore[reportMissingImports]
from onvif import exceptions # pyright: ignore[reportMissingImports]


class ONVIFCameraBase:
    """Base class for ONVIF camera operations with common functionality."""
    
    def __init__(self, ip: str, port: int, username: str, password: str, profile_name: Optional[str] = None) -> None:
        self.camera = ONVIFCamera(ip, port, username, password)
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()
        
        if self.profiles is None:
            raise ValueError(
                "No profiles returned from the camera. Please check connection or credentials."
            )
        
        if profile_name:
            # Find profile by name
            self.profile_token = next(
                (profile.token for profile in self.profiles if profile.Name == profile_name),
                None
            )
            if not self.profile_token:
                raise ValueError(f"Profile '{profile_name}' not found.")
        else:
            self.profile_token = self.profiles[0].token

    def get_ptz_status(self) -> Optional[dict]:
        """Get PTZ status from the camera."""
        try:
            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            return status
        except exceptions.ONVIFError as e:
            log_event(logger, "error", f"Error getting PTZ status: {e}", event_type="error")
            return None

    # def get_current_position(self) -> Tuple[float, float, float]:
    #     """Get current pan, tilt, and zoom position."""
    #     try:
    #         status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
    #         if not status:
    #             raise ValueError(
    #                 "GetStatus() returned None. Check camera connectivity and credentials."
    #             )
    #         if not hasattr(status, "Position"):
    #             raise ValueError(
    #                 "Status object does not contain a 'Position' attribute."
    #             )
            
    #         log_event(logger, "error", f"{status}", event_type="error")
            
    #         current_pan = status.Position.PanTilt.x
    #         current_tilt = status.Position.PanTilt.y
    #         current_zoom = status.Position.Zoom.x
    #         return float(current_pan), float(current_tilt), float(current_zoom)
    #     except Exception as e:
    #         log_event(logger, "error", f"An error occurred while getting current position: {e}", event_type="error")
    #         return 0.0, 0.0, 0.0

    def get_current_position(self) -> Tuple[float, float, float]:
        """Get current pan, tilt, and zoom position with multiple fallback methods."""
        try:
            status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
            if not status:
                raise ValueError("GetStatus() returned None.")
            
            # Method 1: Try normal Position attribute
            if hasattr(status, "Position") and status.Position is not None:
                current_pan = status.Position.PanTilt.x
                current_tilt = status.Position.PanTilt.y
                current_zoom = status.Position.Zoom.x
                return float(current_pan), float(current_tilt), float(current_zoom)
            
            # Method 2: Parse XML elements HIKVision style
            # This is a common workaround for cameras that return XML-like structures
            # in the Position attribute, especially for HIKVision cameras.
            if hasattr(status, '_value_1') and status._value_1:
                import xml.etree.ElementTree as ET
                for element in status._value_1:
                    if element.tag.endswith('Position'):
                        pan_tilt = element.find('.//{http://www.onvif.org/ver10/schema}PanTilt')
                        zoom = element.find('.//{http://www.onvif.org/ver10/schema}Zoom')
                        
                        if pan_tilt is not None and zoom is not None:
                            pan = float(pan_tilt.get('x', 0.0))
                            tilt = float(pan_tilt.get('y', 0.0))
                            zoom_val = float(zoom.get('x', 0.0))
                            return pan, tilt, zoom_val
            
            # Method 3: Try accessing as dictionary
            if isinstance(status, dict) and 'Position' in status:
                pos = status['Position']
                if pos and 'PanTilt' in pos and 'Zoom' in pos:
                    return (
                        float(pos['PanTilt']['x']),
                        float(pos['PanTilt']['y']),
                        float(pos['Zoom']['x'])
                    )
            
            log_event(logger, "warning", "All position parsing methods failed", event_type="warning")
            return 0.0, 0.0, 0.0
            
        except Exception as e:
            log_event(logger, "error", f"Error getting current position: {e}", event_type="error")
            return 0.0, 0.0, 0.0

    def get_zoom_level(self) -> float:
        """Get current zoom level."""
        try:
            _, _, zoom = self.get_current_position()
            return zoom
        except Exception as e:
            log_event(logger, "error", f"An error occurred while getting zoom level: {e}", event_type="error")
            return 0.0

    # def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
    #     """Execute continuous movement with specified velocities."""
    #     try:
    #         request = self.ptz_service.create_type("ContinuousMove")
    #         request.ProfileToken = self.profile_token

    #         status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
    #         if not status:
    #             raise ValueError(
    #                 "GetStatus() returned None. Check camera connectivity and credentials."
    #             )
    #         if not hasattr(status, "Position"):
    #             raise ValueError(
    #                 "Status object does not contain a 'Position' attribute."
    #             )

    #         request.Velocity = status.Position
    #         request.Velocity.PanTilt.x = pan
    #         request.Velocity.PanTilt.y = tilt
    #         request.Velocity.Zoom.x = zoom

    #         self.ptz_service.ContinuousMove(request)
    #     except exceptions.ONVIFError as e:
    #         log_event(logger, "error", f"Error in continuous move: {e}", event_type="error")

    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None:
        """Execute continuous movement with specified velocities."""
        try:
            request = self.ptz_service.create_type("ContinuousMove")
            request.ProfileToken = self.profile_token

            # Build velocity structure manually instead of using status.Position
            request.Velocity = {
                'PanTilt': {'x': pan, 'y': tilt},
                'Zoom': {'x': zoom}
            }

            self.ptz_service.ContinuousMove(request)
        except exceptions.ONVIFError as e:
            log_event(logger, "error", f"Error in continuous move: {e}", event_type="error")

    # def absolute_move(self, pan: float, tilt: float, zoom: float, 
    #                  pan_speed: Optional[float] = None, 
    #                  tilt_speed: Optional[float] = None, 
    #                  zoom_speed: Optional[float] = None) -> None:
    #     """Execute absolute movement to specified position."""
    #     try:
    #         request = self.ptz_service.create_type("AbsoluteMove")
    #         request.ProfileToken = self.profile_token

    #         # status = self.ptz_service.GetStatus({"ProfileToken": self.profile_token})
    #         # if not status:
    #         #     raise ValueError(
    #         #         "GetStatus() returned None. Check camera connectivity and credentials."
    #         #     )
    #         # if not hasattr(status, "Position"):
    #         #     raise ValueError(
    #         #         "Status object does not contain a 'Position' attribute."
    #         #     )

    #         # request.Position = status.Position
    #         # request.Position.PanTilt.x = pan
    #         # request.Position.PanTilt.y = tilt
    #         # request.Position.Zoom.x = zoom

    #         # Construct position explicitly (safest cross-camera approach)
    #         request.Position = self.ptz_service.factory.create('ns0:PTZVector')
    #         request.Position.PanTilt = self.ptz_service.factory.create('ns0:Vector2D')
    #         request.Position.Zoom = self.ptz_service.factory.create('ns0:Vector1D')

    #         request.Position.PanTilt.x = pan
    #         request.Position.PanTilt.y = tilt
    #         request.Position.Zoom.x = zoom


    #         # Set speed if provided
    #         if any([pan_speed, tilt_speed, zoom_speed]):
    #             request.Speed = {
    #                 "PanTilt": {
    #                     "x": pan_speed or 0.5,
    #                     "y": tilt_speed or 0.5
    #                 },
    #                 "Zoom": {"x": zoom_speed or 0.5}
    #             }

    #         self.ptz_service.AbsoluteMove(request)
    #     except exceptions.ONVIFError as e:
    #         logging.error(f"Error in absolute move: {e}")

    
    def absolute_move(self, pan: float, tilt: float, zoom: float, 
                  pan_speed: Optional[float] = None, 
                  tilt_speed: Optional[float] = None, 
                  zoom_speed: Optional[float] = None) -> None:
        """Execute absolute movement to specified position."""
        try:
            request = self.ptz_service.create_type("AbsoluteMove")
            request.ProfileToken = self.profile_token

            # Manually build the correct PTZVector and children using dict-like access
            request.Position = {
                'PanTilt': {'x': pan, 'y': tilt},
                'Zoom': {'x': zoom}
            }

            # Optional: Add movement speed
            if any([pan_speed, tilt_speed, zoom_speed]):
                request.Speed = {
                    'PanTilt': {'x': pan_speed or 0.5, 'y': tilt_speed or 0.5},
                    'Zoom': {'x': zoom_speed or 0.5}
                }

            self.ptz_service.AbsoluteMove(request)
        except exceptions.ONVIFError as e:
            log_event(logger, "error", f"Error in absolute move: {e}", event_type="error")

    def stop_movement(self) -> None:
        """Stop all camera movement."""
        try:
            request = self.ptz_service.create_type("Stop")
            request.ProfileToken = self.profile_token
            request.PanTilt = True
            request.Zoom = True
            self.ptz_service.Stop(request)
        except exceptions.ONVIFError as e:
            log_event(logger, "error", f"Error stopping PTZ movement: {e}", event_type="error")