import cv2
import datetime
import threading
import time
import asyncio
from collections import deque
from detection.object_detection import ObjectDetection
from utils.camera_controller import CameraController
# from routes.socketio_handlers import socketio
from socketio_instance import socketio

class VideoStreaming:
    def __init__(self, rtsp_link, model_name, stream_id):
        # self.app = app
        self.VIDEO = None  # Initialize without opening a stream
        self.MODEL = ObjectDetection()
        # self.db = db
        # self.EventVideo = EventVideo
        self.fps_queue = deque(maxlen=30)
        self.total_frame_count = 0
        self.unsafe_frame_count = 0
        self.frames_written = 0
        self.video_name = None

        self.frame_buffer = deque(maxlen=10)
        self.running = False

        self.lock = threading.Lock()

        self.streams_id = stream_id
        self.rtsp_link = rtsp_link
        self.model_name = model_name

    @property
    def preview(self):
        return self._preview

    @preview.setter
    def preview(self, value):
        self._preview = bool(value)

    @property
    def flipH(self):
        return self._flipH

    @flipH.setter
    def flipH(self, value):
        self._flipH = bool(value)

    @property
    def detect(self):
        return self._detect

    @detect.setter
    def detect(self, value):
        self._detect = bool(value)

    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, value):
        self._exposure = value
        self.VIDEO.set(cv2.CAP_PROP_EXPOSURE, self._exposure)

    @property
    def contrast(self):
        return self._contrast

    @contrast.setter
    def contrast(self, value):
        self._contrast = value
        self.VIDEO.set(cv2.CAP_PROP_CONTRAST, self._contrast)

    def process_video(self, snap, model_name, out, video_count, result_queue):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if self._detect:
            if out is None:
                # Use default FPS of 20 if CAP_PROP_FPS returns 0 or invalid
                fps = self.VIDEO.get(cv2.CAP_PROP_FPS) or 20
                out, self.video_name = self.create_video_writer(snap, timestamp, model_name, fps)
            print("After: ", self.video_name)
            snap, timestamp, finalStatus, inference_time = self.MODEL.detectObj(snap, timestamp, model_name)
            self.total_frame_count += 1
            if finalStatus == "UnSafe" and out is not None:
                out.write(snap)
                self.unsafe_frame_count += 1
                self.frames_written += 1

        result_queue.put((snap, out, self.total_frame_count, timestamp, self.video_name))



    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)  # Open the stream with the given RTSP link
    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20  # Use a default FPS if not available
    #     out = None
    #     frame_interval = int(3 * fps)  # Check status every 3 seconds
    #     record_duration = int(5 * fps)  # Record 5 seconds video
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # # Check if we should save the video
    #         # total_frame_count += 1
    #         # if total_frame_count % frame_interval == 0:
    #         #     unsafe_ratio = unsafe_frame_count / frame_interval if frame_interval else 0
    #         #     if unsafe_ratio >= 0.7:
    #         #         if total_frame_count % record_duration == 0:
    #         #             self.save_event_video(video_name, timestamp, camera_id=None)  # Pass camera_id if needed
    #         #             if out is not None:
    #         #                 out.release()
    #         #                 out = None
    #         #             unsafe_frame_count = 0

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Encode frame for streaming
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #                b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         time.sleep(0.01)

    #     video_capture.release()

    # =========================================
    # =========================================
    # =========================================
    

    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)  # Open the stream with the given RTSP link
    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20  # Use a default FPS if not available
    #     out = None
    #     frame_interval = int(3 * fps)  # Check status every 3 seconds
    #     record_duration = int(5 * fps)  # Record 5 seconds video
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     # Open a new window to display the stream
    #     cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Display the frame in the window
    #         cv2.imshow("Stream", processed_frame)

    #         # Stream over HTTP (if needed)
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #             b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         # Exit condition for the OpenCV window
    #         if cv2.waitKey(1) & 0xFF == ord('q'):
    #             break

    #         time.sleep(0.01)

    #     # Clean up and close the window
    #     video_capture.release()
    #     cv2.destroyAllWindows()
    #     if out is not None:
    #         out.release()

    # =========================================
    # =========================================
    # =========================================


    def show(self, model_name, rtsp_link):
        video_capture = cv2.VideoCapture(rtsp_link)
        if not video_capture.isOpened():
            print(f"Error: Unable to open video stream from {rtsp_link}")
            return

        fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
        out = None
        frame_interval = int(3 * fps)
        record_duration = int(5 * fps)
        total_frame_count = 0
        unsafe_frame_count = 0
        frames_written = 0
        video_name = None
        fps_queue = deque(maxlen=30)

        # Optimize by reducing frame size
        # desired_width = 640
        # desired_height = 480
        # desired_width = 800
        # desired_height = 600
        desired_width = 1280
        desired_height = 720


        cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

        while video_capture.isOpened():
            ret, frame = video_capture.read()
            if not ret:
                print(f"Failed to read from {rtsp_link}")
                break

            # Resize frame to desired dimensions
            frame = cv2.resize(frame, (desired_width, desired_height))

            processed_frame, final_status = self.apply_model(frame, model_name)

            if final_status == "UnSafe":
                if out is None:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    out, video_name = self.create_video_writer(frame, timestamp, model_name, fps)
                out.write(processed_frame)
                unsafe_frame_count += 1
                frames_written += 1

            fps_queue.append(time.time())
            fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
            cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            cv2.imshow("Stream", processed_frame)

            # Exit condition for the OpenCV window
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            time.sleep(0.01)

        video_capture.release()
        cv2.destroyAllWindows()
        if out is not None:
            out.release()


    # def show(self, model_name, rtsp_link):
    #     video_capture = cv2.VideoCapture(rtsp_link)
    #     if not video_capture.isOpened():
    #         print(f"Error: Unable to open video stream from {rtsp_link}")
    #         return

    #     fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
    #     out = None
    #     frame_interval = int(3 * fps)
    #     record_duration = int(5 * fps)
    #     total_frame_count = 0
    #     unsafe_frame_count = 0
    #     frames_written = 0
    #     video_name = None
    #     fps_queue = deque(maxlen=30)

    #     # Desired width and height
    #     # desired_width = 640
    #     # desired_height = 480
    #     desired_width = 800
    #     desired_height = 600

    #     cv2.namedWindow("Stream", cv2.WINDOW_NORMAL)

    #     while video_capture.isOpened():
    #         ret, frame = video_capture.read()
    #         if not ret:
    #             print(f"Failed to read from {rtsp_link}")
    #             break

    #         # Get original frame dimensions
    #         original_height, original_width = frame.shape[:2]

    #         # Calculate aspect ratio of the original frame
    #         aspect_ratio = original_width / original_height

    #         # Calculate the new dimensions while maintaining aspect ratio
    #         if aspect_ratio > 1:  # Wider than tall
    #             new_width = desired_width
    #             new_height = int(desired_width / aspect_ratio)
    #         else:  # Taller than wide or square
    #             new_height = desired_height
    #             new_width = int(desired_height * aspect_ratio)

    #         # Resize the frame to the new dimensions
    #         frame_resized = cv2.resize(frame, (new_width, new_height))

    #         # Apply model detection logic
    #         processed_frame, final_status = self.apply_model(frame_resized, model_name)

    #         # Save unsafe events
    #         if final_status == "UnSafe":
    #             if out is None:
    #                 timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    #                 out, video_name = self.create_video_writer(processed_frame, timestamp, model_name, fps)
    #             out.write(processed_frame)
    #             unsafe_frame_count += 1
    #             frames_written += 1

    #         # Calculate FPS and display it on the frame
    #         fps_queue.append(time.time())
    #         fps = len(fps_queue) / (fps_queue[-1] - fps_queue[0]) if len(fps_queue) > 1 else 0.0
    #         cv2.putText(processed_frame, f"FPS: {fps:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #         # Display the frame in the window
    #         cv2.imshow("Stream", processed_frame)

    #         # Stream over HTTP (if needed)
    #         encoded_frame = cv2.imencode(".jpg", processed_frame)[1].tobytes()
    #         yield (b'--frame\r\n'
    #             b'Content-Type: image/jpeg\r\n\r\n' + encoded_frame + b'\r\n')

    #         # Exit condition for the OpenCV window
    #         if cv2.waitKey(1) & 0xFF == ord('q'):
    #             break

    #         time.sleep(0.01)

    #     # Clean up and close the window
    #     video_capture.release()
    #     cv2.destroyAllWindows()
    #     if out is not None:
    #         out.release()





    def apply_model(self, frame, model_name):
        # Detect objects using the specified model
        model = self.MODEL.models.get(model_name)
        if not model:
            raise ValueError(f"Model '{model_name}' not found!")

        results = model(frame)
        final_status = "Safe"

        if model_name == "PPE":
            final_status = self.MODEL.detect_ppe(frame, results)
        elif model_name == "Ladder":
            final_status = self.MODEL.detect_ladder(frame, results)
        elif model_name == "MobileScaffolding":
            final_status = self.MODEL.detect_mobile_scaffolding(frame, results)
        elif model_name == "Scaffolding":
            final_status = self.MODEL.detect_scaffolding(frame, results)
        elif model_name == "CuttingWelding":
            final_status = self.MODEL.detect_cutting_welding(frame, results)

        return frame, final_status

    def create_video_writer(self, frame, timestamp, model_name, output_fps):
        video_name1 = f"./static/unsafe/video_{model_name}_{timestamp}.mp4"  # Save videos as MP4 with timestamp
        video_name = f"/unsafe/video_{model_name}_{timestamp}.mp4"
        height, width, _ = frame.shape
        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        return cv2.VideoWriter(video_name1, fourcc, output_fps, (width, height)), video_name

    # def save_event_video(self, video_path, timestamp, camera_id):
    #     with self.app.app_context():
    #         event_video = self.EventVideo(timestamp=timestamp, video_path=video_path, camera_id=camera_id)
    #         try:
    #             self.db.session.add(event_video)
    #             self.db.session.commit()
    #         except Exception as e:
    #             self.db.session.rollback()
    #             print(f"Error saving video event: {e}")
    def start_stream(self):
        self.running = True
        threading.Thread(target=self.generate_frames, args=("rtsp://admin:1q2w3e4r.@218.54.201.82:554/idis?trackid=2", "PPE"), daemon=True).start()
        threading.Thread(target=self.process_and_emit_frames, args=("PPE",), daemon=True).start()

    def stop_streaming(self): 
        self.running = False


    def generate_frames(self, rtsp_link, model_name):
        # Open the RTSP video stream
        video_capture = cv2.VideoCapture(self.rtsp_link)
        if not video_capture.isOpened():
            print(f"Error: Unable to open video stream from {self.rtsp_link}")
            return

        fps = video_capture.get(cv2.CAP_PROP_FPS) or 20
        desired_width, desired_height = 1280, 720  # Set desired dimensions

        while self.running and video_capture.isOpened():
            ret, frame = video_capture.read()
            if not ret:
                print(f"Failed to read from {self.rtsp_link}")
                break

            # Resize frame to desired dimensions (perform this as early as possible)
            frame = cv2.resize(frame, (desired_width, desired_height))

            # Lock the buffer and add the frame to the buffer
            with self.lock:
                self.frame_buffer.append(frame)

        video_capture.release()

    def process_and_emit_frames(self, model_name):
        while self.running:
            with self.lock:
                if self.frame_buffer:
                    frame = self.frame_buffer.popleft()
                else:
                    frame = None

            if frame is not None:
                # Apply your detection model
                processed_frame, final_status = self.apply_model(frame, self.model_name)

                # Encode frame in JPEG format with lower quality for faster transmission
                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                frame_data = buffer.tobytes()

                # Emit frame to all connected clients
                # socketio.emit('frame', {'image': frame_data}, namespace='/video')
                socketio.emit(f'frame-{self.streams_id}', {'image': frame_data}, namespace='/video', room=self.streams_id)

            else:
                # If no frames are in the buffer, wait for a short time
                asyncio.sleep(0.001)

    # def apply_model(self, frame, model_name):
    #     # Simulate model processing (replace with actual model inference)
    #     processed_frame = frame  # No change for now
    #     final_status = "safe"  # Placeholder status
    #     return processed_frame, final_status

    # def stream_frames(self):
    #     while self.running:
    #         if self.frame_buffer:
    #             frame = self.frame_buffer.popleft()
    #             yield (b'--frame\r\n'
    #                    b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    #         else:
    #             time.sleep(0.001)  # Slight delay if buffer is empty

    def stop(self):
        self.running = False

