import os
import cv2
import numpy as np
from typing import Tuple, Optional
from config import ASSETS_DIR, FRAME_WIDTH


FONT_DIR_BARLOW = os.path.join(ASSETS_DIR, "fonts", "Barlow-Regular.ttf")
FONT_DIR_ROBOTO = os.path.join(ASSETS_DIR, "fonts", "RobotoMono-Regular.ttf")
THICKNESS = -1

freetype_roboto = cv2.freetype.createFreeType2()  # type: ignore
freetype_roboto.loadFontData(FONT_DIR_ROBOTO, 0)

freetype_barlow = cv2.freetype.createFreeType2()  # type: ignore
freetype_barlow.loadFontData(FONT_DIR_BARLOW, 0)

def draw_text_with_background(image, text, position, bg_color, t_type="label"):

    font_height = 20
    pad = 4

    (text_wh, baseline) = freetype_barlow.getTextSize(text, font_height, THICKNESS)
    text_width, text_height = text_wh

    x, y = position
    rect_left = x
    rect_top = y
    rect_right = x + text_width + 2 * pad
    rect_bottom = y + text_height + 2 * pad

    y_offset = int((rect_bottom - rect_top) / 2)

    if t_type in ["fps", "reason", "status"]:
        rect_left = int(FRAME_WIDTH - ((rect_right - rect_left) + 40))
        rect_right = FRAME_WIDTH - 40

    rect_top = rect_top - y_offset
    rect_bottom = rect_bottom - y_offset

    cv2.rectangle(
        image,
        (rect_left, rect_top),
        (rect_right, rect_bottom),
        bg_color,
        cv2.FILLED,
    )

    text_baseline_x = x + pad
    text_baseline_y = y - y_offset

    if t_type in ["fps", "reason", "status"]:
        text_baseline_x = rect_left + pad
        text_baseline_y = y - y_offset

    freetype_barlow.putText(
        image,
        text,
        (text_baseline_x, text_baseline_y),
        font_height,
        (255, 255, 255),
        THICKNESS,
        cv2.LINE_AA,
        False,  # bottomLeftOrigin
    )


# Define constant colors
COLOR_BLACK = (0, 0, 0)          # Black
COLOR_WHITE = (255, 255, 255)    # White
COLOR_YELLOW = (0, 255, 255)     # Yellow (BGR)
COLOR_CYAN = (255, 255, 0)       # Cyan (BGR)
COLOR_MAGENTA = (255, 0, 255)    # Magenta (BGR)

def get_optimal_text_color_v2(image, position, text_size):
    """
    Analyze the region of the image where text will be placed and 
    determine the optimal text color (black, white, yellow, or other contrasting colors)
    """
    x, y = position
    width, height = text_size
    
    # Create a region of interest (ROI)
    # Ensure coordinates are within image bounds
    x1 = max(0, int(x))
    y1 = max(0, int(y - height))
    x2 = min(image.shape[1], int(x + width))
    y2 = min(image.shape[0], int(y))
    
    # Extract the region
    roi = image[y1:y2, x1:x2]
    
    # If ROI is empty (e.g., out of bounds), use default white
    if roi.size == 0:
        return COLOR_WHITE
    
    # Calculate average color and brightness of the region
    if len(image.shape) == 3:  # Color image
        avg_color = np.mean(roi, axis=(0, 1))
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:  # Already grayscale
        avg_color = np.array([np.mean(roi)] * 3)
        gray_roi = roi
    
    avg_brightness = np.mean(gray_roi)
    
    # Get dominant blue, green, red values (remember OpenCV uses BGR)
    b, g, r = avg_color
    
    # Choose color based on background characteristics
    if avg_brightness < 85:  # Very dark background
        return COLOR_YELLOW  # Yellow for very dark backgrounds
    elif avg_brightness > 170:  # Very bright background
        return COLOR_BLACK  # Black for very bright backgrounds
    elif b > 150 and g > 150:  # Yellowish background
        # return COLOR_MAGENTA  # Magenta for yellowish backgrounds
        return COLOR_YELLOW  # Magenta for yellowish backgrounds
    elif r > 150 and b > 150:  # Purplish background
        return COLOR_CYAN  # Cyan for purplish backgrounds
    elif avg_brightness > 127:  # Moderately bright background
        return COLOR_BLACK  # Black for moderately bright backgrounds
    else:  # Moderately dark background
        return COLOR_WHITE  # White for moderately dark backgrounds

def get_optimal_text_color(image, position, text_size):
    """
    Analyze the region of the image where text will be placed and 
    determine the optimal text color (light or dark)
    """
    x, y = position
    width, height = text_size
    
    # Create a region of interest (ROI)
    # Ensure coordinates are within image bounds
    x1 = max(0, int(x))
    y1 = max(0, int(y - height))
    x2 = min(image.shape[1], int(x + width))
    y2 = min(image.shape[0], int(y))
    
    # Extract the region
    roi = image[y1:y2, x1:x2]
    
    # If ROI is empty (e.g., out of bounds), use default white
    if roi.size == 0:
        return (255, 255, 255)
    
    # Calculate average brightness of the region
    if len(image.shape) == 3:  # Color image
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:  # Already grayscale
        gray_roi = roi
    
    avg_brightness = np.mean(gray_roi)
    
    # Choose color based on brightness
    # If background is bright, use dark text, otherwise use light text
    if avg_brightness > 127:
        return (0, 0, 0)  # Black text for bright backgrounds
    else:
        return (255, 255, 255)  # White text for dark backgrounds




def draw_text_with_freetype(image, text, position, font_height, color=None, thickness=THICKNESS, right_aligned=True):
    """Helper function to draw text using FreeType with optional right alignment and adaptive color"""
    x_pos, y_pos = position
    
    # Get text size to calculate right-aligned position
    (text_wh, _) = freetype_roboto.getTextSize(text, font_height, thickness)
    text_width, text_height = text_wh
    
    if right_aligned:
        padding = 40  # Padding from right edge
        x_pos = FRAME_WIDTH - text_width - padding
    
    # If color is None, determine optimal color based on background
    if color is None:
        color = get_optimal_text_color_v2(image, (x_pos, y_pos), (text_width, text_height))
    
    freetype_roboto.putText(
        image,
        text,
        (int(x_pos), int(y_pos)),
        font_height,
        color,
        thickness,
        cv2.LINE_AA,
        False  # bottomLeftOrigin
    )

def draw_status_info(image, reasons=[], fps=None):
    # Set starting position (y only since x will be calculated for right alignment)
    y_pos = 20
    line_height = 30
    x_pos = 0  # Will be calculated for each text element

    font_height = 22
    
    # Determine status based on reasons list
    status = "unsafe" if reasons and len(reasons) > 0 else "safe"
    
    # Status color is fixed regardless of background (semantic meaning)
    status_color = (0, 0, 255) if status == "unsafe" else (0, 255, 0)  # Red for unsafe, Green for safe
    
    # Draw status header with adaptive color
    draw_text_with_freetype(
        image,
        "[status]",
        (x_pos, y_pos),
        font_height,
        None  # Adaptive color
    )
    y_pos += line_height
    
    # Status value keeps its semantic color (red/green)
    draw_text_with_freetype(
        image,
        status,
        (x_pos, y_pos),
        font_height,
        status_color,
        -1
    )
    y_pos += line_height * 1.5
    
    # Draw reasons if any with adaptive color
    if reasons and len(reasons) > 0:
        draw_text_with_freetype(
            image,
            "[reason(s)]",
            (x_pos, y_pos),
            font_height,
            None  # Adaptive color
        )
        y_pos += line_height
        
        # Draw each reason on a new line with adaptive color
        for reason in reasons:
            draw_text_with_freetype(
                image,
                reason,
                (x_pos, y_pos),
                font_height,
                None  # Adaptive color
            )
            y_pos += line_height
    
    # Draw FPS if provided with adaptive color
    if fps is not None:
        y_pos += line_height * 0.5  # Add some spacing
        draw_text_with_freetype(
            image,
            f"{int(fps)} fps",
            (x_pos, y_pos),
            font_height,
            None  # Adaptive color
        )
    
    return image
