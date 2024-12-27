import cv2

def detect_intrusion(hazard_zones, person_bboxes=[]):
    """
    Detects intrusions based on person bounding boxes and hazard zones.

    Parameters:
    - person_boxes: List of person bounding boxes, each in the format (x_min, y_min, x_max, y_max).
    - hazard_zones: List of hazard zones, each represented as a polygon (list of points).

    Returns:
    - List of person boxes that are intruding into hazard zones.
    """
    intrusions = []

    for box in person_bboxes:
        # Calculate the bottom mid-point of the person box
        x_min, y_min, x_max, y_max = box
        bottom_mid_point = ((x_min + x_max) // 2, y_max)

        # Check if the bottom mid-point is inside any hazard zone
        for hazard_zone in hazard_zones:
            if cv2.pointPolygonTest(hazard_zone, bottom_mid_point, False) >= 0:
                intrusions.append(box)
                break  # Stop checking other hazard zones for this person box

    return intrusions