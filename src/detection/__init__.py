import os
import cv2
from config import ASSETS_DIR, FRAME_WIDTH


FONT_DIR = os.path.join(ASSETS_DIR, "fonts", "Barlow-Regular.ttf")

THICKNESS = -1


def draw_text_with_background(image, text, position, bg_color, t_type="label"):
    freetype = cv2.freetype.createFreeType2()  # type: ignore
    freetype.loadFontData(FONT_DIR, 0)

    font_height = 20
    pad = 4

    (text_wh, baseline) = freetype.getTextSize(text, font_height, THICKNESS)
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

    freetype.putText(
        image,
        text,
        (text_baseline_x, text_baseline_y),
        font_height,
        (255, 255, 255),
        THICKNESS,
        cv2.LINE_AA,
        False,  # bottomLeftOrigin
    )
