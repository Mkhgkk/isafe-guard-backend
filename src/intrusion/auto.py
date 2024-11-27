import os
import cv2
import numpy as np
from collections import deque

class SafeAreaTracker:
    # _instance = None

    # def __new__(cls, *args, **kwargs):
    #     if not cls._instance:
    #         cls._instance = super(SafeAreaTracker, cls).__new__(cls)
    #     return cls._instance

    def __init__(self):
        # if not hasattr(self, 'initialized'):  
        self.previous_safe_area = None
        self.reference_frame = None
        self.orb = cv2.ORB_create()
        self.homography_buffer = deque(maxlen=50)
        self.safe_area_box = None
        # self.initialized = True

    def update_safe_area(self, reference_frame, safe_area_box):
        self.reference_frame = reference_frame
        self.safe_area_box = safe_area_box

        self.previous_safe_area = None
        self.homography_buffer = deque(maxlen=50)

    def draw_safe_area(self, frame): 
        if self.reference_frame is None or self.safe_area_box is None:
            return frame
        
        current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        keypoints_ref, descriptors_ref = self.orb.detectAndCompute(self.reference_frame, None)
        keypoints_curr, descriptors_curr = self.orb.detectAndCompute(current_frame, None)

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(descriptors_ref, descriptors_curr)
        matches = sorted(matches, key=lambda x: x.distance)

        good_matches = [m for m in matches if m.distance < 25] 

        if len(good_matches) < 10:
            return frame
        
        pts_ref = np.float32([keypoints_ref[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        pts_curr = np.float32([keypoints_curr[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

        homography_matrix, mask = cv2.findHomography(pts_ref, pts_curr, cv2.RANSAC, 3.0)

        if homography_matrix is None:
            return frame
        
        motion_magnitude = np.mean(np.linalg.norm(pts_curr - pts_ref, axis=2))
        alpha = max(0.5, min(0.9, 1 - (motion_magnitude / 50)))

        self.homography_buffer.append(homography_matrix)

        # stabilized_homography = np.mean(self.homography_buffer, axis=0)
        # stabilized_homography = alpha * stabilized_homography + (1 - alpha) * homography_matrix

        safe_area_ref = np.float32(self.safe_area_box).reshape(-1, 1, 2)

        safe_area_curr = cv2.perspectiveTransform(safe_area_ref, homography_matrix)

        if self.previous_safe_area is not None:
            safe_area_curr = alpha * safe_area_curr + (1 - alpha) * self.previous_safe_area

        self.previous_safe_area = safe_area_curr

        cv2.polylines(frame, [np.int32(safe_area_curr)], True, (0, 255, 255), 2)

        return frame
