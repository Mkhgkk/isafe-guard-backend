import os
import cv2
import numpy as np

script_directory = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join('intrusion', 'captured_frame.jpg')

# Load the reference frame and the current frame
reference_frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
# current_frame = cv2.imread('transformed.png', cv2.IMREAD_GRAYSCALE)

# Initialize the ORB detector
orb = cv2.ORB_create()

def draw_safe_area(frame):
    # Detect keypoints and compute descriptors
    current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    keypoints_ref, descriptors_ref = orb.detectAndCompute(reference_frame, None)
    keypoints_curr, descriptors_curr = orb.detectAndCompute(current_frame, None)

    # Match descriptors using BFMatcher
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(descriptors_ref, descriptors_curr)
    matches = sorted(matches, key=lambda x: x.distance)

    # Extract matched keypoint coordinates
    pts_ref = np.float32([keypoints_ref[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    pts_curr = np.float32([keypoints_curr[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    # Estimate the homography matrix
    homography_matrix, _ = cv2.findHomography(pts_ref, pts_curr, cv2.RANSAC, 5.0)

    # Define the safe area in the center of the reference frame
    # height, width = reference_frame.shape
    # x_center, y_center = width // 2, height // 2
    # safe_area_size = 100  # Size of the safe area (e.g., 100x100 pixels)
    # x1, y1 = x_center - safe_area_size // 2, y_center - safe_area_size // 2
    # x2, y2 = x_center + safe_area_size // 2, y_center + safe_area_size // 2
    # safe_area_ref = np.float32([
    #     [x1, y1], [x2, y1], [x2, y2], [x1, y2]
    # ]).reshape(-1, 1, 2)
    safe_area_ref = np.float32([[602, 238], [852, 238], [852, 542], [602, 542]]).reshape(-1, 1, 2)

    # Transform the safe area coordinates to the current frame
    safe_area_curr = cv2.perspectiveTransform(safe_area_ref, homography_matrix)

    # Draw the safe area on the reference frame
    # reference_frame_color = cv2.cvtColor(reference_frame, cv2.COLOR_GRAY2BGR)
    # cv2.polylines(reference_frame_color, [np.int32(safe_area_ref)], True, (0, 255, 0), 2)

    # Draw the transformed safe area on the current frame
    # current_frame_color = cv2.cvtColor(current_frame, cv2.COLOR_GRAY2BGR)
    cv2.polylines(frame, [np.int32(safe_area_curr)], True, (0, 255, 0), 2)

    text_position = tuple(np.int32(safe_area_curr[0][0]))

    # # Add the text "intrusion zone"
    # cv2.putText(
    #     frame,                       
    #     "intrusion zone",            
    #     text_position,               
    #     cv2.FONT_HERSHEY_SIMPLEX,    
    #     1,                         
    #     (0, 255, 0),                 
    #     2,                          
    #     # cv2.LINE_AA                  
    # )

                        

    return frame

    # # Save the images
    # cv2.imwrite('reference_frame_with_safe_area.png', reference_frame_color)
    # cv2.imwrite('current_frame_with_transformed_safe_area.png', current_frame_color)

    # # Display for verification (optional)
    # cv2.imshow('Reference Frame with Safe Area', reference_frame_color)
    # cv2.imshow('Current Frame with Transformed Safe Area', current_frame_color)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
