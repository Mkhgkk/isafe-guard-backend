from onvif import ONVIFCamera, exceptions
import time
import queue
import threading
import numpy as np

class PTZAutoTracker:
    def __init__(self, cam_ip, ptz_port, ptz_username, ptz_password):
        # Initialize the ONVIF camera
        # self.camera = ONVIFCamera("192.168.0.149", 80, "root", "fsnetworks1!")
        # self.camera = ONVIFCamera("223.171.86.249", 80, "admin", "1q2w3e4r.")
        self.camera = ONVIFCamera(cam_ip, ptz_port, ptz_username, ptz_password)
        self.ptz_service = self.camera.create_ptz_service()
        self.media_service = self.camera.create_media_service()
        self.profiles = self.media_service.GetProfiles()
        self.profile_token = self.profiles[0].token

        # Define tolerance levels for movement (initial dynamic tolerance)
        self.center_tolerance_x = 0.1
        self.center_tolerance_y = 0.1

        # Define PTZ movement speeds
        self.pan_velocity = 0.8
        self.tilt_velocity = 0.8
        self.zoom_velocity = 0.02

        # Zoom limits
        self.min_zoom = 0.1  # Minimum zoom level
        self.max_zoom = 0.3  # Maximum zoom level to avoid over-zoom

        # Action throttling parameters
        self.last_move_time = time.time()
        self.move_throttle_time = 0.5  # Throttle moves to at most every 0.5 seconds

        # Define timeouts and default behaviors
        self.no_object_timeout = 5  # Time in seconds to wait before taking action when no objects are detected
        self.last_detection_time = time.time()
        self.default_position = {'pan': 0, 'tilt': 0, 'zoom': self.min_zoom}  # Home position for the camera
        self.is_moving = False
        self.move_queue = queue.Queue()
        self.move_thread = threading.Thread(target=self._process_move_queue)
        self.move_thread.start()

        self.is_at_default_position = False

        # PTZ state and metrics
        self.ptz_metrics = {
            "zoom_level": self.min_zoom,  # Start at minimum zoom level
        }
        self.calibrating = False  # To track if the camera is calibrating

        self.home_pan = 0
        self.home_tilt = 0
        self.home_zoom = self.min_zoom

    def update_default_position(self, pan, tilt, zoom):
        self.home_pan = pan
        self.home_tilt = tilt
        self.home_zoom = zoom


    def get_ptz_status(self):
        """Get the current PTZ status."""
        try:
            status = self.ptz_service.GetStatus({'ProfileToken': self.profile_token})
            return status
        except exceptions.ONVIFError as e:
            print(f"Error getting PTZ status: {e}")
            return None

    def calculate_movement(self, frame_width, frame_height, bboxes):
        """Calculate the necessary pan, tilt, and zoom adjustments to keep the objects centered."""
        if not bboxes:
            return 0, 0, 0  # No movement if no bounding boxes

        # Compute frame center
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2

        # Calculate combined center of all objects
        bbox_centers_x = []
        bbox_centers_y = []
        bbox_areas = []

        for bbox in bboxes:
            x1, y1, x2, y2 = bbox

            # Calculate width, height, and center of each bounding box
            bbox_width = x2 - x1
            bbox_height = y2 - y1
            bbox_center_x = x1 + bbox_width / 2
            bbox_center_y = y1 + bbox_height / 2

            bbox_centers_x.append(bbox_center_x)
            bbox_centers_y.append(bbox_center_y)
            bbox_areas.append(bbox_width * bbox_height)

        # Calculate average center for pan and tilt
        avg_center_x = np.mean(bbox_centers_x)
        avg_center_y = np.mean(bbox_centers_y)

        # Calculate the normalized deltas for pan and tilt
        delta_x = (avg_center_x - frame_center_x) / frame_width
        delta_y = (avg_center_y - frame_center_y) / frame_height

        # Update tolerance dynamically based on zoom level
        self.center_tolerance_x = max(0.05, self.center_tolerance_x * (1 - self.ptz_metrics["zoom_level"]))
        self.center_tolerance_y = max(0.05, self.center_tolerance_y * (1 - self.ptz_metrics["zoom_level"]))

        # Determine pan and tilt directions with threshold to avoid jitter
        pan_direction = self._calculate_pan_tilt(delta_x, self.center_tolerance_x, self.pan_velocity)
        tilt_direction = self._calculate_pan_tilt(delta_y, self.center_tolerance_y, self.tilt_velocity, invert=True)

        # Calculate zoom adjustment to keep all objects within frame
        zoom_direction = self._calculate_zoom(frame_width, frame_height, bbox_areas, bbox_centers_x, bbox_centers_y)

        return pan_direction, tilt_direction, zoom_direction

    def _calculate_pan_tilt(self, delta, tolerance, velocity, invert=False):
        """Calculate the direction and amount of pan or tilt required."""
        if abs(delta) > tolerance:
            direction = -velocity * delta if invert else velocity * delta
            return max(-1.0, min(1.0, direction))  # Normalize to [-1, 1]
        return 0

    def _calculate_zoom(self, frame_width, frame_height, bbox_areas, bbox_centers_x, bbox_centers_y):
        """Calculate the zoom adjustment required to keep the objects in frame."""
        frame_area = frame_width * frame_height

        # Target area ratio for object size in the frame to prevent over-zoom or under-zoom
        min_target_area_ratio = 0.03  # Minimum area ratio threshold
        max_target_area_ratio = 0.1   # Maximum area ratio threshold

        # Calculate average area of all bounding boxes
        total_bbox_area = np.sum(bbox_areas)
        current_area_ratio = total_bbox_area / frame_area

        # Calculate the farthest object from the center
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2
        max_distance_from_center = max(
            np.sqrt(((bbox_center_x - frame_center_x) / frame_width) ** 2 +
                    ((bbox_center_y - frame_center_y) / frame_height) ** 2)
            for bbox_center_x, bbox_center_y in zip(bbox_centers_x, bbox_centers_y)
        )

        # Define thresholds for zooming in and out based on area ratio and distance from center
        zoom_in_threshold = min_target_area_ratio * (1 - self.ptz_metrics["zoom_level"])
        zoom_out_threshold = max_target_area_ratio * (1 + self.ptz_metrics["zoom_level"])

        zoom_direction = 0

        if current_area_ratio < zoom_in_threshold and self.ptz_metrics["zoom_level"] < self.max_zoom:
            zoom_direction = self.zoom_velocity * (1 - max_distance_from_center)  # Zoom in to make objects larger
        elif current_area_ratio > zoom_out_threshold and self.ptz_metrics["zoom_level"] > self.min_zoom:
            zoom_direction = -self.zoom_velocity * (1 + max_distance_from_center)  # Zoom out to keep objects in view

        # Ensure zoom level stays within limits
        new_zoom_level = self.ptz_metrics["zoom_level"] + zoom_direction
        self.ptz_metrics["zoom_level"] = max(self.min_zoom, min(self.max_zoom, new_zoom_level))

        return zoom_direction

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

            # Update zoom level metrics
            self.ptz_metrics["zoom_level"] += zoom

            # Send the continuous move command
            self.ptz_service.ContinuousMove(request)
            self.is_moving = True  # Update movement state
        except exceptions.ONVIFError as e:
            print(f"Error in continuous move: {e}")

    def stop_movement(self):
        """Stop PTZ movement."""
        if self.is_moving:  # Only stop if currently moving
            try:
                request = self.ptz_service.create_type('Stop')
                request.ProfileToken = self.profile_token
                request.PanTilt = True
                request.Zoom = True
                self.ptz_service.Stop(request)
                self.is_moving = False  # Update movement state
            except exceptions.ONVIFError as e:
                print(f"Error stopping PTZ movement: {e}")

    def move_to_default_position(self):
        """Move the camera to the default 'home' position."""

        home_pan = -0.550611138
        home_tilt = -0.531818211
        home_zoom = 0.0499999933
        try:
            request = self.ptz_service.create_type('AbsoluteMove')
            request.ProfileToken = self.profile_token

            # Initialize Position properly
            request.Position = self.ptz_service.GetStatus({'ProfileToken': self.profile_token}).Position
            request.Position.PanTilt.x = self.home_pan
            request.Position.PanTilt.y = self.home_tilt
            request.Position.Zoom.x = self.home_zoom

            # Update zoom level metrics
            # self.ptz_metrics["zoom_level"] = self.default_position['zoom']
            self.ptz_metrics["zoom_level"] = self.home_zoom

            # Send the absolute move command
            self.ptz_service.AbsoluteMove(request)
        except exceptions.ONVIFError as e:
            print(f"Error moving to default position: {e}")

    def reset_camera_position(self):
        """Stop any current movement and move the camera to its default position."""
        self.stop_movement()
        self.move_to_default_position()

    

    def track(self, frame_width, frame_height, bboxes=None):
        """Main tracking method."""
        if bboxes is None or len(bboxes) == 0:
            # No object detected
            current_time = time.time()
            if current_time - self.last_detection_time > self.no_object_timeout and not self.is_at_default_position:
                # Zoom out to default position for broader monitoring
                # self.stop_movement()  # Stop any current movement
                # self.move_to_default_position()  # Move to default position
                thread = threading.Thread(target=self.reset_camera_position, args=())
                thread.start()

                self.is_at_default_position = True
                
                print("No object detected. Moving to default zoom level.")
            else:
                print("No object detected. Waiting...")
            return
        
        # Object(s) detected; update last detection time
        self.last_detection_time = time.time()

        # Throttle movement commands to prevent jitter
        if time.time() - self.last_move_time < self.move_throttle_time:
            print("Throttling movement to prevent jitter.")
            return

        pan, tilt, zoom = self.calculate_movement(frame_width, frame_height, bboxes)
        
        # If no movement is needed, stop the camera
        if pan == 0 and tilt == 0 and zoom == 0:
            self.stop_movement()
        else:
            # Enqueue movement to smooth out commands
            self._enqueue_move(pan, tilt, zoom)

        # Update the last move time to current time
        self.last_move_time = time.time()
        self.is_at_default_position = False

    def _enqueue_move(self, pan, tilt, zoom):
        """Enqueue a move command to the move queue."""
        self.move_queue.put((pan, tilt, zoom))

    def _process_move_queue(self):
        """Process the move queue and execute PTZ commands."""
        while True:
            try:
                pan, tilt, zoom = self.move_queue.get(timeout=1)
                self.continuous_move(pan, tilt, zoom)
                time.sleep(0.1)  # Introduce a small delay to smooth movements
                self.move_queue.task_done()
            except queue.Empty:
                continue

    def _calibrate_camera(self):
        """Calibrate the camera for precise movements."""
        self.calibrating = True
        # Perform calibration steps (e.g., moving to preset positions)
        # ...
        self.calibrating = False

    def _predict_movement_time(self, pan, tilt):
        """Predict the time required for a movement based on pan and tilt."""
        combined_movement = abs(pan) + abs(tilt)
        return np.dot(self.move_coefficients, [1, combined_movement])

