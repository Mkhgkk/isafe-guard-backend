"""
Face blurring utilities for privacy protection.

This module provides functions to blur faces in detection systems,
helping to protect worker privacy while maintaining safety monitoring capabilities.
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional


def blur_face_region(
    image: np.ndarray,
    box: List[int],
    blur_ratio: float = 0.4,
    blur_kernel_size: Tuple[int, int] = (7, 7),
) -> None:
    """Blur the top portion of a person's bounding box for privacy.

    This function modifies the image in-place by blurring the top portion
    of the person's bounding box, typically covering the face area.

    Args:
        image: Image array (modified in-place)
        box: Person bounding box [x1, y1, x2, y2]
        blur_ratio: Ratio of box height to blur (default: 0.4 = top 40%)
        blur_kernel_size: Kernel size for blur operation (default: (7, 7))

    Returns:
        None (modifies image in-place)

    Example:
        >>> import numpy as np
        >>> image = np.ones((480, 640, 3), dtype=np.uint8) * 255
        >>> box = [100, 100, 200, 300]
        >>> blur_face_region(image, box)
        # Top 40% of box [100:100, 100:200] is now blurred
    """
    x1, y1, x2, y2 = box
    blur_height = int(blur_ratio * (y2 - y1))
    y1_blur = y1
    y2_blur = y1 + blur_height

    # Validate blur region
    if y2_blur > y1_blur and x2 > x1:
        face_region = image[y1_blur:y2_blur, x1:x2]
        if face_region.size > 0:
            blurred = cv2.blur(face_region, blur_kernel_size)
            image[y1_blur:y2_blur, x1:x2] = blurred


def should_blur_person(
    label: str,
    role_prefixes: Optional[List[str]] = None,
) -> bool:
    """Determine if a person should have their face blurred based on their role.

    By default, blurs faces for Workers, Drivers, and Signalers to protect privacy.
    Vehicles and other objects are not blurred.

    Args:
        label: Person label (e.g., "Worker with helmet_id:5", "Driver_id:3")
        role_prefixes: List of role prefixes to blur (default: ["Worker", "Driver", "Signaler"])

    Returns:
        True if face should be blurred, False otherwise

    Example:
        >>> should_blur_person("Worker with helmet_id:5")
        True
        >>> should_blur_person("Vehicle_id:10")
        False
        >>> should_blur_person("Technician_id:2", role_prefixes=["Worker", "Technician"])
        True
    """
    if role_prefixes is None:
        role_prefixes = ["Worker", "Driver", "Signaler"]

    return any(label.startswith(role) for role in role_prefixes)
