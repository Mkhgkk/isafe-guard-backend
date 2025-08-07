import os
import cv2
import numpy as np
from utils.logging_config import get_logger, log_event
import threading
from typing import Tuple, Optional
from config import ASSETS_DIR, FRAME_WIDTH

logger = get_logger(__name__)

FONT_DIR_BARLOW = os.path.join(ASSETS_DIR, "fonts", "Barlow-Regular.ttf")
FONT_DIR_ROBOTO = os.path.join(ASSETS_DIR, "fonts", "RobotoMono-Regular.ttf")
THICKNESS = -1

# Global locks for thread safety
freetype_lock = threading.Lock()
opencv_text_lock = threading.Lock()

# Thread-safe FreeType initialization
def _init_freetype_fonts():
    """Initialize FreeType fonts in a thread-safe manner"""
    with freetype_lock:
        try:
            freetype_roboto = cv2.freetype.createFreeType2()
            freetype_roboto.loadFontData(FONT_DIR_ROBOTO, 0)
            
            freetype_barlow = cv2.freetype.createFreeType2()
            freetype_barlow.loadFontData(FONT_DIR_BARLOW, 0)
            
            return freetype_roboto, freetype_barlow
        except Exception as e:
            log_event(logger, "error", f"Failed to initialize FreeType fonts: {e}", event_type="error")
            return None, None

# Thread-local storage for FreeType instances
thread_local = threading.local()

def get_thread_local_fonts():
    """Get thread-local FreeType font instances"""
    if not hasattr(thread_local, 'freetype_roboto') or thread_local.freetype_roboto is None:
        thread_local.freetype_roboto, thread_local.freetype_barlow = _init_freetype_fonts()
    
    return thread_local.freetype_roboto, thread_local.freetype_barlow

# Fallback to standard OpenCV fonts if FreeType fails
def draw_text_opencv_fallback(image, text, position, color, font_scale=0.7, thickness=2):
    """Fallback text rendering using standard OpenCV (thread-safe)"""
    with opencv_text_lock:
        try:
            font = cv2.FONT_HERSHEY_SIMPLEX
            
            # Get text size for background
            (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            
            x, y = position
            # Draw background rectangle
            cv2.rectangle(image, 
                         (x - 5, y - text_height - 10),
                         (x + text_width + 5, y + baseline),
                         (0, 0, 0), -1)
            
            # Draw text
            cv2.putText(image, text, position, font, font_scale, color, thickness, cv2.LINE_AA)
            
        except Exception as e:
            log_event(logger, "error", f"OpenCV fallback text rendering error: {e}", event_type="error")

def draw_text_with_background(image, text, position, bg_color, t_type="label"):
    """Thread-safe version of draw_text_with_background"""
    
    # Try FreeType first, fallback to OpenCV if it fails
    freetype_roboto, freetype_barlow = get_thread_local_fonts()
    
    if freetype_barlow is None:
        # Fallback to OpenCV
        color = (255, 255, 255)  # White text
        draw_text_opencv_fallback(image, text, position, color)
        return
    
    with freetype_lock:
        try:
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
            
        except Exception as e:
            log_event(logger, "error", f"FreeType text rendering error: {e}", event_type="error")
            # Fallback to OpenCV
            color = (255, 255, 255)
            draw_text_opencv_fallback(image, text, position, color)

# Define constant colors
COLOR_BLACK = (0, 0, 0)          # Black
COLOR_WHITE = (255, 255, 255)    # White
COLOR_YELLOW = (0, 255, 255)     # Yellow (BGR)
COLOR_CYAN = (255, 255, 0)       # Cyan (BGR)
COLOR_MAGENTA = (255, 0, 255)    # Magenta (BGR)

def get_optimal_text_color_v2(image, position, text_size):
    """
    Thread-safe version: Analyze the region and determine optimal text color
    """
    try:
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
            return COLOR_YELLOW  # Yellow for yellowish backgrounds
        elif r > 150 and b > 150:  # Purplish background
            return COLOR_CYAN  # Cyan for purplish backgrounds
        elif avg_brightness > 127:  # Moderately bright background
            return COLOR_BLACK  # Black for moderately bright backgrounds
        else:  # Moderately dark background
            return COLOR_WHITE  # White for moderately dark backgrounds
            
    except Exception as e:
        log_event(logger, "error", f"Error in get_optimal_text_color_v2: {e}", event_type="error")
        return COLOR_WHITE  # Safe default

def get_optimal_text_color(image, position, text_size):
    """
    Thread-safe version: Determine optimal text color (light or dark)
    """
    try:
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
            
    except Exception as e:
        log_event(logger, "error", f"Error in get_optimal_text_color: {e}", event_type="error")
        return (255, 255, 255)  # Safe default

def draw_text_with_freetype(image, text, position, font_height, color=None, thickness=THICKNESS, right_aligned=True):
    """Thread-safe helper function to draw text using FreeType with optional right alignment and adaptive color"""
    
    freetype_roboto, freetype_barlow = get_thread_local_fonts()
    
    if freetype_roboto is None:
        # Fallback to OpenCV
        final_color = color if color is not None else (255, 255, 255)
        draw_text_opencv_fallback(image, text, position, final_color)
        return
    
    with freetype_lock:
        try:
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
            
        except Exception as e:
            log_event(logger, "error", f"FreeType text rendering error in draw_text_with_freetype: {e}", event_type="error")
            # Fallback to OpenCV
            final_color = color if color is not None else (255, 255, 255)
            draw_text_opencv_fallback(image, text, position, final_color)

def draw_status_info(image, reasons=[],  fps=None, num_person_bboxes=0, final_status="Safe"):
    """Thread-safe version of draw_status_info"""
    try:
        # Set starting position (y only since x will be calculated for right alignment)
        y_pos = 20
        line_height = 30
        x_pos = 0  # Will be calculated for each text element

        font_height = 22
        section_spacing = line_height * 1.5  # Consistent spacing between sections
        
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
        y_pos += section_spacing
        
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

            y_pos += (section_spacing - line_height)  # Adjust for last reason's line_height

        # Draw number of detected persons
        if num_person_bboxes > 0:
            draw_text_with_freetype(
                image,
                "[worker(s)]",
                (x_pos, y_pos),
                font_height,
                None  # Adaptive color
            )
            y_pos += line_height
            
            draw_text_with_freetype(
                image,
                str(num_person_bboxes),
                (x_pos, y_pos),
                font_height,
                None  # Adaptive color
            )
            y_pos += section_spacing
        
        # Draw FPS if provided with adaptive color
        if fps is not None:
            # Add spacing before FPS if workers section was shown
            if num_person_bboxes <= 0:
                y_pos += section_spacing  # Add section spacing if workers section wasn't shown
            
            draw_text_with_freetype(
                image,
                f"{int(fps)} fps",
                (x_pos, y_pos),
                font_height,
                None  # Adaptive color
            )
        
    except Exception as e:
        log_event(logger, "error", f"Error in draw_status_info: {e}", event_type="error")
        # Fallback: draw simple text using OpenCV
        try:
            with opencv_text_lock:
                status = "unsafe" if reasons and len(reasons) > 0 else "safe"
                status_color = (0, 0, 255) if status == "unsafe" else (0, 255, 0)
                
                cv2.putText(image, f"Status: {status}", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
                
                if fps is not None:
                    cv2.putText(image, f"FPS: {int(fps)}", (10, 60), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    
        except Exception as fallback_error:
            log_event(logger, "error", f"Fallback text rendering also failed: {fallback_error}", event_type="error")
    
    return image

# Additional utility function for safe text rendering across all camera streams
def safe_draw_simple_text(image, text, position, color=(255, 255, 255), font_scale=0.7):
    """Simple, guaranteed thread-safe text drawing using standard OpenCV"""
    with opencv_text_lock:
        try:
            cv2.putText(image, text, position, cv2.FONT_HERSHEY_SIMPLEX, 
                       font_scale, color, 2, cv2.LINE_AA)
        except Exception as e:
            log_event(logger, "error", f"Simple text rendering error: {e}", event_type="error")

