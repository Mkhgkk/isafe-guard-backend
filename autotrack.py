from onvif import ONVIFCamera, exceptions
import time

class PTZAutoTracker:
    def __init__(self):
        # Initialize the ONVIF camera
        self.camera = ONVIFCamera("192.168.0.133", 80, "root", "fsnetworks1!")
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()
        self.profile_token = self.profiles[0].token

        # Define tolerance levels for movement
        self.center_tolerance_x = 0.1  # 10% of frame width
        self.center_tolerance_y = 0.1  # 10% of frame height

        # Define PTZ movement speeds
        self.pan_velocity = 0.1
        self.tilt_velocity = 0.1
        self.zoom_velocity = 0.1

        # Define timeouts and default behaviors
        self.no_object_timeout = 5  # Time in seconds to wait before taking action when no objects are detected
        self.last_detection_time = time.time()
        self.default_position = {'pan': 0, 'tilt': 0, 'zoom': 0}  # Home position for the camera

    def get_ptz_status(self):
        """Get the current PTZ status."""
        try:
            status = self.ptz_service.GetStatus({'ProfileToken': self.profile_token})
            return status
        except exceptions.ONVIFError as e:
            print(f"Error getting PTZ status: {e}")
            return None

    def calculate_movement(self, frame_width, frame_height, bbox):
        """Calculate the necessary pan, tilt, and zoom adjustments."""
        x1, y1, x2, y2 = bbox

        # Calculate width and height of the bounding box
        bbox_width = x2 - x1
        bbox_height = y2 - y1

        # Calculate the center of the bounding box
        bbox_center_x = x1 + bbox_width / 2
        bbox_center_y = y1 + bbox_height / 2

        # Compute frame center
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2

        # Calculate the normalized deltas for pan and tilt
        delta_x = (bbox_center_x - frame_center_x) / frame_width
        delta_y = (bbox_center_y - frame_center_y) / frame_height

        # Determine pan and tilt directions
        pan_direction = 0
        tilt_direction = 0

        if delta_x > self.center_tolerance_x:
            pan_direction = self.pan_velocity
        elif delta_x < -self.center_tolerance_x:
            pan_direction = -self.pan_velocity

        if delta_y > self.center_tolerance_y:
            tilt_direction = -self.tilt_velocity
        elif delta_y < -self.center_tolerance_y:
            tilt_direction = self.tilt_velocity

        # Calculate zoom adjustment based on object size (example logic)
        bbox_area = bbox_width * bbox_height
        frame_area = frame_width * frame_height
        zoom_direction = 0
        if bbox_area < 0.05 * frame_area:  # If object is too small
            zoom_direction = self.zoom_velocity
        elif bbox_area > 0.2 * frame_area:  # If object is too large
            zoom_direction = -self.zoom_velocity

        return pan_direction, tilt_direction, zoom_direction

    def continuous_move(self, pan, tilt, zoom):
        """Send continuous move command to PTZ camera."""
        try:
            request = self.ptz_service.create_type('ContinuousMove')
            request.ProfileToken = self.profile_token

            # Ensure Velocity and PanTilt are properly initialized
            request.Velocity = self.ptz_service.GetStatus({'ProfileToken': self.profile_token}).Position
            request.Velocity.PanTilt.x = pan
            request.Velocity.PanTilt.y = tilt
            request.Velocity.Zoom.x = zoom

            # Send the continuous move command
            self.ptz_service.ContinuousMove(request)
        except exceptions.ONVIFError as e:
            print(f"Error in continuous move: {e}")

    def stop_movement(self):
        """Stop PTZ movement."""
        try:
            request = self.ptz_service.create_type('Stop')
            request.ProfileToken = self.profile_token
            request.PanTilt = True
            request.Zoom = True
            self.ptz_service.Stop(request)
        except exceptions.ONVIFError as e:
            print(f"Error stopping PTZ movement: {e}")

    def move_to_default_position(self):
        """Move the camera to the default 'home' position."""
        try:
            request = self.ptz_service.create_type('AbsoluteMove')
            request.ProfileToken = self.profile_token

            # Initialize Position properly
            request.Position = self.ptz_service.GetStatus({'ProfileToken': self.profile_token}).Position
            request.Position.PanTilt.x = self.default_position['pan']
            request.Position.PanTilt.y = self.default_position['tilt']
            request.Position.Zoom.x = self.default_position['zoom']

            # Send the absolute move command
            self.ptz_service.AbsoluteMove(request)
        except exceptions.ONVIFError as e:
            print(f"Error moving to default position: {e}")

    def track(self, frame_width, frame_height, bbox=None):
        """Main tracking method."""
        if bbox is None:
            # No object detected
            current_time = time.time()
            if current_time - self.last_detection_time > self.no_object_timeout:
                self.stop_movement()  # Stop any current movement
                self.move_to_default_position()  # Move to default position
                print("No object detected. Moving to default position.")
            else:
                print("No object detected. Waiting...")
            return
        
        # Object detected; update last detection time
        self.last_detection_time = time.time()

        pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bbox)
        
        # If no movement is needed, stop the camera
        if pan == 0 and tilt == 0 and zoom == 0:
            self.stop_movement()
        else:
            # Otherwise, move the camera
            self.continuous_move(pan, tilt, zoom)


# # Example usage
# if __name__ == "__main__":
#     tracker = PTZAutoTracker()

#     # Dummy frame dimensions
#     frame_width, frame_height = 1920, 1080

#     while True:
#         # Example: replace `bbox` with real detection data
#         bbox = [800, 450, 1100, 650]  # Example bounding box (x1, y1, x2, y2)

#         tracker.track(frame_width, frame_height, bbox)
#         time.sleep(1)  # Simulate frame processing delay
