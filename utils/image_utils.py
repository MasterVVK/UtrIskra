import logging
import os

from PIL import Image, ImageDraw, ImageFont

from config import FONTS_PATH

logger = logging.getLogger(__name__)


def add_date_to_image(image_path: str, date_text: str):
    """Добавляет водяной знак с датой в правый нижний угол изображения."""
    try:
        font_path = os.path.join(FONTS_PATH, "Roboto-Regular.ttf")
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Шрифт '{font_path}' не найден.")

        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        font_size = int(min(img.size) * 0.025)
        font = ImageFont.truetype(font_path, font_size)

        text_position = (img.size[0] - font_size * len(date_text) - 10,
                         img.size[1] - font_size - 10)
        shadow_offset = 2
        draw.text((text_position[0] + shadow_offset, text_position[1] + shadow_offset),
                  date_text, font=font, fill=(0, 0, 0))
        draw.text(text_position, date_text, font=font, fill=(255, 255, 255))
        img.save(image_path)
        logger.info("Дата '%s' добавлена на изображение %s", date_text, image_path)
    except Exception as e:
        logger.error("Ошибка при добавлении даты на изображение: %s", e)
        raise
