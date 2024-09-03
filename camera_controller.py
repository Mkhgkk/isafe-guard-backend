from onvif import ONVIFCamera

class CameraController:
    def __init__(self, ip, port, username, password):
        self.camera = ONVIFCamera(ip, port, username, password)
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()
        self.profile_token = self.profiles[0].token
    
    def get_zoom_level(self):
        """Retrieve the current zoom level of the camera."""
        try:
            status = self.ptz_service.GetStatus({'ProfileToken': self.profile_token})
            current_zoom = status.Position.Zoom.x
            return current_zoom
        except Exception as e:
            print(f"An error occurred while getting zoom level: {e}")
            return 0.0  # Return a default zoom level if there's an error

    def get_current_position(self):
        """Retrieve the current PTZ status to get the current Pan, Tilt, and Zoom positions."""
        try:
            status = self.ptz_service.GetStatus({'ProfileToken': self.profile_token})
            current_pan = status.Position.PanTilt.x
            current_tilt = status.Position.PanTilt.y
            current_zoom = status.Position.Zoom.x
            return current_pan, current_tilt, current_zoom
        except Exception as e:
            print(f"An error occurred while getting current position: {e}")
            return 0.0, 0.0, 0.0  # Return a default position if there's an error

    def move_camera(self, direction, zoom_amount=None):
        """Function to move camera based on the direction input or zoom to a specific level."""
        
        if direction in ['zoom_in', 'zoom_out'] and zoom_amount is not None:
            # Use AbsoluteMove for zoom
            absolute_move_request = self.ptz_service.create_type('AbsoluteMove')
            absolute_move_request.ProfileToken = self.profile_token

            # Get current Pan, Tilt, and Zoom positions
            current_pan, current_tilt, current_zoom = self.get_current_position()

            # Define the absolute position, keeping current Pan and Tilt, and setting new Zoom
            absolute_move_request.Position = {
                'PanTilt': {'x': current_pan, 'y': current_tilt},
                'Zoom': {'x': zoom_amount}
            }
            absolute_move_request.Speed = {'Zoom': {'x': 0.5}}  # Optional: Define zoom speed

            # Execute the AbsoluteMove command
            try:
                self.ptz_service.AbsoluteMove(absolute_move_request)
                print(f"Camera zoomed to level {zoom_amount}.")
            except Exception as e:
                print(f"An error occurred during zoom: {e}")
        
        else:
            # Use ContinuousMove for pan and tilt
            continuous_move_request = self.ptz_service.create_type('ContinuousMove')
            continuous_move_request.ProfileToken = self.profile_token

            # Initialize the PTZ speed vector correctly
            continuous_move_request.Velocity = {
                'PanTilt': {'x': 0.0, 'y': 0.0},
                'Zoom': {'x': 0.0}
            }

            # Define the speed for each direction
            pan_speed = 0.1  # Speed for pan movement
            tilt_speed = 0.1  # Speed for tilt movement

            # Set the speed for each direction
            if direction == 'up':
                continuous_move_request.Velocity['PanTilt']['y'] = tilt_speed
            elif direction == 'down':
                continuous_move_request.Velocity['PanTilt']['y'] = -tilt_speed
            elif direction == 'left':
                continuous_move_request.Velocity['PanTilt']['x'] = -pan_speed
            elif direction == 'right':
                continuous_move_request.Velocity['PanTilt']['x'] = pan_speed

            # Execute the ContinuousMove command
            try:
                self.ptz_service.ContinuousMove(continuous_move_request)
                print(f"Camera moving {direction} continuously.")
            except Exception as e:
                print(f"An error occurred during movement: {e}")

    def stop_camera(self):
        """Function to stop the camera movement."""
        stop_request = self.ptz_service.create_type('Stop')
        stop_request.ProfileToken = self.profile_token
        stop_request.PanTilt = True  # Stop PanTilt movement
        stop_request.Zoom = True     # Stop Zoom movement
        
        try:
            self.ptz_service.Stop(stop_request)
            print("Camera movement stopped.")
        except Exception as e:
            print(f"An error occurred while stopping: {e}")
