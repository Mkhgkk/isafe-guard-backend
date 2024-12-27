import cv2
import numpy as np
from collections import deque
from threading import Thread
import torch
from .models.matching import Matching
from .models.utils import frame2tensor


class SafeAreaTracker:
    def __init__(self):
        # self.previous_safe_area = None
        self.reference_frame = None
        self.homography_buffer = deque(maxlen=50)
        self.safe_area_box = None
        self.ref_tensor = None

        # SuperGlue configuration
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        config = {
            'superpoint': {
                'nms_radius': 4,
                'keypoint_threshold': 0.01,  # Increased threshold for fewer keypoints
                'max_keypoints': 500  # Limit keypoints
            },
            'superglue': {
                'weights': 'indoor',
                'sinkhorn_iterations': 10,  # Reduced iterations
                'match_threshold': 0.3  # Looser threshold
            }
        }
        self.device = device
        self.matching = Matching(config).eval().to(device)

    def update_safe_area(self, reference_frame, safe_area_box):
        self.reference_frame = reference_frame
        self.safe_area_box = safe_area_box

        ref_gray = cv2.cvtColor(self.reference_frame, cv2.COLOR_BGR2GRAY)
        self.ref_tensor = frame2tensor(ref_gray, self.device)

        # self.previous_safe_area = None
        self.homography_buffer.clear()

    def draw_safe_area(self, frame):
        if self.reference_frame is None or not self.safe_area_box:
            return frame

        ref_gray = cv2.cvtColor(self.reference_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        curr_tensor = frame2tensor(curr_gray, self.device)

        with torch.no_grad():
            pred = self.matching({'image0': self.ref_tensor, 'image1': curr_tensor})

        kpts_ref = pred['keypoints0'][0].cpu().numpy()
        kpts_curr = pred['keypoints1'][0].cpu().numpy()
        matches = pred['matches0'][0].cpu().numpy()

        valid = matches > -1
        matched_kpts_ref = kpts_ref[valid]
        matched_kpts_curr = kpts_curr[matches[valid]]

        if len(matched_kpts_ref) < 10:
            return frame

        homography_matrix, _ = cv2.findHomography(
            matched_kpts_ref, matched_kpts_curr, cv2.RANSAC, 2.0  # Reduced threshold
        )

        if homography_matrix is None:
            return frame

        overlay = frame.copy()

        for safe_area_box in self.safe_area_box:
            safe_area_ref = np.float32(safe_area_box).reshape(-1, 1, 2)
            safe_area_curr = cv2.perspectiveTransform(safe_area_ref, homography_matrix)

            # Fill the polygon on the overlay
            cv2.fillPoly(overlay, [np.int32(safe_area_curr)], (0, 255, 255))

            # Draw the outline of the polygon
            cv2.polylines(frame, [np.int32(safe_area_curr)], True, (0, 255, 255), 2)

        # Blend the overlay with the original frame
        alpha = 0.4
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        return frame
