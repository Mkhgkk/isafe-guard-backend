import os
import cv2
import numpy as np
from collections import deque

script_directory = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join('intrusion', 'captured_frame.jpg')

# Load the reference frame
safe_area_box = [[690, 167], [935, 167], [935, 444], [690, 444]]
reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

# Initialize the ORB detector
orb = cv2.ORB_create()

# Initialize a buffer to store homography matrices for smoothing
homography_buffer = deque(maxlen=5)  # Buffer size for smoothing

# Initialize previous safe area for smoothing
previous_safe_area = None

def draw_safe_area(frame):
    global previous_safe_area

    # Convert current frame to grayscale
    current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Detect keypoints and compute descriptors
    keypoints_ref, descriptors_ref = orb.detectAndCompute(reference_frame, None)
    keypoints_curr, descriptors_curr = orb.detectAndCompute(current_frame, None)

    # Match descriptors using BFMatcher
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(descriptors_ref, descriptors_curr)
    matches = sorted(matches, key=lambda x: x.distance)

    # Filter matches by distance
    good_matches = [m for m in matches if m.distance < 25]  # Adjust threshold

    # Proceed only if enough good matches are found
    if len(good_matches) < 10:
        return frame

    # Extract matched keypoint coordinates
    pts_ref = np.float32([keypoints_ref[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    pts_curr = np.float32([keypoints_curr[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

    # Estimate the homography matrix
    homography_matrix, mask = cv2.findHomography(pts_ref, pts_curr, cv2.RANSAC, 3.0)

    if homography_matrix is None:
        return frame

    # Compute motion magnitude
    motion_magnitude = np.mean(np.linalg.norm(pts_curr - pts_ref, axis=2))
    alpha = max(0.5, min(0.9, 1 - (motion_magnitude / 50)))  # Adjust for responsiveness

    # Add homography matrix to the buffer for smoothing
    homography_buffer.append(homography_matrix)

    # Compute the stabilized homography matrix
    stabilized_homography = np.mean(homography_buffer, axis=0)
    stabilized_homography = alpha * stabilized_homography + (1 - alpha) * homography_matrix

    # Define the safe area in the reference frame
    safe_area_ref = np.float32(safe_area_box).reshape(-1, 1, 2)

    # Transform the safe area coordinates to the current frame
    safe_area_curr = cv2.perspectiveTransform(safe_area_ref, stabilized_homography)

    # Apply smoothing to the safe area coordinates
    if previous_safe_area is not None:
        safe_area_curr = alpha * safe_area_curr + (1 - alpha) * previous_safe_area

    previous_safe_area = safe_area_curr

    # Draw the transformed safe area on the current frame
    cv2.polylines(frame, [np.int32(safe_area_curr)], True, (0, 255, 255), 2)

    # Add the text "Intrusion Zone"
    # text_position = tuple(np.int32(safe_area_curr[0][0]))
    # cv2.putText(
    #     frame,
    #     "Intrusion Zone",
    #     text_position,
    #     cv2.FONT_HERSHEY_SIMPLEX,
    #     1,
    #     (0, 255, 0),
    #     2
    # )

    return frame

