import cv2


def draw_text_with_background(image, text, position, font_scale, color, thickness):
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x, text_y = position
    box_coords = (
        (text_x, text_y),
        (text_x + text_size[0] + 4, text_y - text_size[1] - 4),
    )
    cv2.rectangle(image, box_coords[0], box_coords[1], color, cv2.FILLED)
    cv2.putText(
        image,
        text,
        (text_x, text_y - 2),
        font,
        font_scale,
        (255, 255, 255),
        thickness,
    )
