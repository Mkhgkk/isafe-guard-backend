import os
import cv2
from config import ASSETS_DIR


FONT_DIR = os.path.join(ASSETS_DIR, "fonts", "Barlow-Regular.ttf")


def draw_text_with_background(image, text, position, font_scale, bg_color, thickness):
    """
    position: (x, y) = TOP-LEFT corner where we want the background rectangle.
    This function will draw the rectangle *and* the text within it.
    """

    freetype = cv2.freetype.createFreeType2()  # type: ignore
    freetype.loadFontData(FONT_DIR, 0)

    font_height = 20
    pad = 4

    (text_wh, baseline) = freetype.getTextSize(text, font_height, thickness)
    text_width, text_height = text_wh

    x, y = position
    rect_left = x
    rect_top = y
    rect_right = x + text_width + 2 * pad
    rect_bottom = y + text_height + 2 * pad

    offset = int((rect_bottom - rect_top) / 2)

    rect_top = rect_top - offset
    rect_bottom = rect_bottom - offset

    cv2.rectangle(
        image,
        (rect_left, rect_top),
        (rect_right, rect_bottom),
        bg_color,
        cv2.FILLED,
    )

    text_baseline_x = x + pad
    text_baseline_y = y - offset

    freetype.putText(
        image,
        text,
        (text_baseline_x, text_baseline_y),
        font_height,
        (255, 255, 255),
        -1,
        cv2.LINE_AA,
        False,  # bottomLeftOrigin
    )
