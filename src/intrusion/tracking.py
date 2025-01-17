import cv2
import numpy as np
from collections import deque
from threading import Thread
import torch
from .models.matching import Matching
from .models.utils import frame2tensor
from typing import Optional, List, Tuple


class SafeAreaTracker:
    def __init__(self) -> None:
        self.reference_frame: Optional[np.ndarray] = None
        self.homography_buffer: deque[np.ndarray] = deque(maxlen=50)
        self.safe_area_box: Optional[List[np.ndarray]] = None
        self.ref_tensor: Optional[torch.Tensor] = None

        device: str = "cuda" if torch.cuda.is_available() else "cpu"
        config = {
            "superpoint": {
                "nms_radius": 4,
                "keypoint_threshold": 0.01,
                "max_keypoints": 500,
            },
            "superglue": {
                "weights": "indoor",
                "sinkhorn_iterations": 10,
                "match_threshold": 0.3,
            },
        }
        self.device: str = device
        self.matching: Matching = Matching(config).eval().to(device)

    def update_safe_area(
        self, reference_frame: np.ndarray, safe_area_box: List[np.ndarray]
    ) -> None:
        self.reference_frame = reference_frame
        self.safe_area_box = safe_area_box

        ref_gray: np.ndarray = cv2.cvtColor(self.reference_frame, cv2.COLOR_BGR2GRAY)
        self.ref_tensor = frame2tensor(ref_gray, self.device)

        self.homography_buffer.clear()

    def draw_safe_area(self, frame: np.ndarray) -> np.ndarray:
        if self.reference_frame is None or not self.safe_area_box:
            return frame

        ref_gray: np.ndarray = cv2.cvtColor(self.reference_frame, cv2.COLOR_BGR2GRAY)
        curr_gray: np.ndarray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        curr_tensor: torch.Tensor = frame2tensor(curr_gray, self.device)

        with torch.no_grad():
            pred = self.matching({"image0": self.ref_tensor, "image1": curr_tensor})

        kpts_ref: np.ndarray = pred["keypoints0"][0].cpu().numpy()
        kpts_curr: np.ndarray = pred["keypoints1"][0].cpu().numpy()
        matches: np.ndarray = pred["matches0"][0].cpu().numpy()

        valid: np.ndarray = matches > -1
        matched_kpts_ref: np.ndarray = kpts_ref[valid]
        matched_kpts_curr: np.ndarray = kpts_curr[matches[valid]]

        if len(matched_kpts_ref) < 10:
            return frame

        homography_matrix, _ = cv2.findHomography(
            matched_kpts_ref, matched_kpts_curr, cv2.RANSAC, 2.0
        )

        if homography_matrix is None:
            return frame

        overlay: np.ndarray = frame.copy()

        for safe_area_box in self.safe_area_box:
            safe_area_ref: np.ndarray = np.float32(safe_area_box).reshape(-1, 1, 2)
            safe_area_curr: np.ndarray = cv2.perspectiveTransform(
                safe_area_ref, homography_matrix
            )

            cv2.fillPoly(overlay, [np.int32(safe_area_curr)], (0, 255, 255))
            cv2.polylines(frame, [np.int32(safe_area_curr)], True, (0, 255, 255), 2)

        alpha: float = 0.4
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        return frame

    def get_transformed_safe_areas(self, frame: np.ndarray) -> List[np.ndarray]:
        transformed_hazard_zones: List[np.ndarray] = []
        if self.reference_frame is None or not self.safe_area_box:
            return []

        ref_gray: np.ndarray = cv2.cvtColor(self.reference_frame, cv2.COLOR_BGR2GRAY)
        curr_gray: np.ndarray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        curr_tensor: torch.Tensor = frame2tensor(curr_gray, self.device)

        with torch.no_grad():
            pred = self.matching({"image0": self.ref_tensor, "image1": curr_tensor})

        kpts_ref: np.ndarray = pred["keypoints0"][0].cpu().numpy()
        kpts_curr: np.ndarray = pred["keypoints1"][0].cpu().numpy()
        matches: np.ndarray = pred["matches0"][0].cpu().numpy()

        valid: np.ndarray = matches > -1
        matched_kpts_ref: np.ndarray = kpts_ref[valid]
        matched_kpts_curr: np.ndarray = kpts_curr[matches[valid]]

        if len(matched_kpts_ref) < 10:
            return []

        homography_matrix, _ = cv2.findHomography(
            matched_kpts_ref, matched_kpts_curr, cv2.RANSAC, 2.0
        )

        if homography_matrix is None:
            return []

        for safe_area_box in self.safe_area_box:
            safe_area_ref: np.ndarray = np.float32(safe_area_box).reshape(-1, 1, 2)
            safe_area_curr: np.ndarray = cv2.perspectiveTransform(
                safe_area_ref, homography_matrix
            )
            transformed_hazard_zones.append(np.int32(safe_area_curr))

        return transformed_hazard_zones

    def draw_safe_area_on_frame(
        self, frame: np.ndarray, transformed_hazard_zones: List[np.ndarray]
    ) -> np.ndarray:
        if not transformed_hazard_zones:
            return frame

        overlay: np.ndarray = frame.copy()

        for safe_area_curr in transformed_hazard_zones:
            cv2.fillPoly(overlay, [safe_area_curr], (0, 255, 255))
            cv2.polylines(frame, [safe_area_curr], True, (0, 255, 255), 2)

        alpha: float = 0.4
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        return frame
