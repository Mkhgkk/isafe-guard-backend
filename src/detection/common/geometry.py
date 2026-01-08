"""
Geometry utilities for detection systems.

This module provides geometric transformation and calculation functions
shared across different detectors.
"""

import cv2
import numpy as np
from typing import List, Tuple

# Default homography transformation points (can be overridden or configured)
# TODO: Move this to a configuration file or make it configurable per stream
DEFAULT_CLICKED_PTS = [(500, 300), (700, 300), (750, 500), (560, 600)]
DEFAULT_REAL_WORLD_COORDS = [[0, 0], [2, 0], [2, 4.5], [0, 4.5]]

def get_homography_matrix(
    image_coords: List[Tuple[int, int]] = DEFAULT_CLICKED_PTS,
    world_coords: List[List[float]] = DEFAULT_REAL_WORLD_COORDS
) -> np.ndarray:
    """Get perspective transform matrix."""
    src_pts = np.float32(image_coords)
    dst_pts = np.float32(world_coords)
    return cv2.getPerspectiveTransform(src_pts, dst_pts)

# Initialize default matrix
_default_homography_matrix = get_homography_matrix()

def get_bottom_center(box: List[int]) -> np.ndarray:
    """Get bottom center point of bounding box.
    
    Args:
        box: [x1, y1, x2, y2]
        
    Returns:
        Numpy array of shape (1, 1, 2) containing point coordinates
    """
    x1, y1, x2, y2 = box
    return np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32)

def get_worker_center(box: List[int]) -> np.ndarray:
    """Get center point of worker bounding box.
    
    Args:
        box: [x1, y1, x2, y2]
        
    Returns:
        Numpy array [x, y]
    """
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)

def transform_to_world(pt: np.ndarray, matrix: np.ndarray = _default_homography_matrix) -> np.ndarray:
    """Transform image coordinates to world coordinates.
    
    Args:
        pt: Point array from get_bottom_center
        matrix: Homography matrix
        
    Returns:
        World coordinates [x, y]
    """
    return cv2.perspectiveTransform(pt, matrix)[0][0]

def get_vehicle_ground_edges(box: List[int]) -> List[np.ndarray]:
    """Get vehicle ground edge points for proximity calculation.
    
    Args:
        box: [x1, y1, x2, y2]
        
    Returns:
        List of 3 points (bottom-center, bottom-left, bottom-right)
        Each point is shape (1, 1, 2)
    """
    x1, y1, x2, y2 = box
    return [
        np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32),
        np.array([[[x1, y2]]], dtype=np.float32),
        np.array([[[x2, y2]]], dtype=np.float32),
    ]
