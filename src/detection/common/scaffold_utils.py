"""
Scaffolding safety check utilities.

This module validates safety rules related to scaffolding, such as
vertical area violations and hook usage.
"""

import cv2
import numpy as np
from typing import List, Tuple, Set, Dict, Any, Optional
from detection import draw_text_with_background

def check_vertical_area_violations(
    worker_boxes: List[Tuple[int, int, int, int]],
    frame_width: int,
    frame_height: int
) -> List[Set[int]]:
    """Identify groups of workers violating vertical area safety rules.
    
    Checks if workers are stacked vertically in a way that poses a risk.
    
    Args:
        worker_boxes: List of bounding boxes [x1, y1, x2, y2]
        frame_width: Width of the video frame
        frame_height: Height of the video frame
        
    Returns:
        List of sets, where each set contains indices of workers in a specific violation group.
    """
    vertical_groups: List[Set[int]] = []
    
    for i, box1 in enumerate(worker_boxes):
        for j, box2 in enumerate(worker_boxes):
            if i == j:
                continue
                
            # Check vertical overlap
            
            # Check if one worker is above another
            center_y_1 = (box1[1] + box1[3]) / 2
            center_y_2 = (box2[1] + box2[3]) / 2
            
            # Check if center of one is below the bottom of the other (since Y increases downwards)
            is_vertically_stacked = (center_y_1 > box2[3]) or (center_y_2 > box1[3])
            
            if is_vertically_stacked:
                # Check horizontal overlap with expanded range
                width1 = box1[2] - box1[0]
                expanded_min_x1 = box1[0] - width1 / 2
                expanded_max_x1 = box1[2] + width1 / 2
                
                # Check intersection of horizontal intervals
                horizontal_overlap = (expanded_min_x1 < box2[2]) and (expanded_max_x1 > box2[0])
                
                if horizontal_overlap:
                    # Find or create group for these workers
                    group_found = False
                    for group in vertical_groups:
                        if i in group or j in group:
                            group.add(i)
                            group.add(j)
                            group_found = True
                            break
                    if not group_found:
                        vertical_groups.append({i, j})
                        
    return vertical_groups

def check_missing_hooks(
    worker_count: int,
    hook_count: int
) -> int:
    """Calculate potential missing hooks.
    
    Args:
        worker_count: Number of workers requiring hooks
        hook_count: Number of hooks detected
        
    Returns:
        Number of missing hooks (min 0)
    """
    return max(0, worker_count - hook_count)

def process_scaffolding_safety(
    image: np.ndarray,
    scaffolding_boxes: List[List[int]],
    worker_positions: List[Tuple[Any, List[int]]],
    hook_boxes: List[List[int]],
    frame_width: int,
    frame_height: int
) -> Tuple[bool, List[str]]:
    """Process high-level scaffolding safety logic.
    
    Identifies workers in scaffolding, checks for vertical stacking violations
    and missing hooks, and draws relevant warnings on the image.
    
    Args:
        image: Image array (modified in-place)
        scaffolding_boxes: List of scaffolding bounding boxes
        worker_positions: List of (world_center, box) tuples for workers
        hook_boxes: List of hook bounding boxes
        frame_width: Frame width
        frame_height: Frame height
        
    Returns:
        Tuple (is_unsafe, new_reasons)
        - is_unsafe: True if any scaffolding violation is found
        - new_reasons: List of violation strings identified
    """
    is_unsafe = False
    reasons = []

    if not scaffolding_boxes:
        return False, []

    # Identify workers that are within scaffolding bounds
    workers_in_scaffolding: List[int] = []
    
    # worker_positions is (world_center, box)
    for i, (_, w_box) in enumerate(worker_positions):
        for scaff_box in scaffolding_boxes:
            # Check if worker box is fully within scaffolding box
            if (
                w_box[0] >= scaff_box[0]
                and w_box[1] >= scaff_box[1]
                and w_box[2] <= scaff_box[2]
                and w_box[3] <= scaff_box[3]
            ):
                workers_in_scaffolding.append(i)
                break
    
    if not workers_in_scaffolding:
        # No workers in scaffolding, checks generally not applicable
        # (Though technically hooks without workers is fine, and verticals need >1 worker)
        return False, []

    # Get boxes for workers in scaffolding
    scaffold_worker_boxes = [worker_positions[i][1] for i in workers_in_scaffolding]
    
    # 1. Check Vertical Area Violations
    # Get groups (sets of indices within the scaffold_worker_boxes list)
    violation_groups_local_indices = check_vertical_area_violations(
        scaffold_worker_boxes, frame_width, frame_height
    )
    
    if violation_groups_local_indices:
        is_unsafe = True
        reasons.append("same_vertical_area")

        # Draw warning boxes around groups
        for group in violation_groups_local_indices:
            if len(group) > 1:
                # Group indices refer to scaffold_worker_boxes list
                group_boxes = [scaffold_worker_boxes[local_idx] for local_idx in group]
                
                min_x = min(box[0] for box in group_boxes)
                min_y = min(box[1] for box in group_boxes)
                max_x = max(box[2] for box in group_boxes)
                max_y = max(box[3] for box in group_boxes)

                padding = 20
                min_x = max(0, min_x - padding)
                min_y = max(0, min_y - padding)
                max_x = min(frame_width, max_x + padding)
                max_y = min(frame_height, max_y + padding)

                cv2.rectangle(image, (min_x, min_y), (max_x, max_y), (0, 0, 255), 4)
                draw_text_with_background(
                    image,
                    "VERTICAL AREA VIOLATION",
                    (min_x, min_y - 10),
                    (0, 0, 255),
                )

    # 2. Check Missing Hooks
    workers_count = len(workers_in_scaffolding)
    hooks_count = len(hook_boxes)
    missing_hooks = check_missing_hooks(workers_count, hooks_count)

    if missing_hooks > 0:
        is_unsafe = True
        reasons.append("missing_hook")

    return is_unsafe, reasons
