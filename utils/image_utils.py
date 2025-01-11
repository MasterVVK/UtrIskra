import os
import datetime
import base64
from PIL import Image, ImageDraw, ImageFont
import logging
from config import IMAGES_PATH, FONTS_PATH

# Настройка логирования
logger = logging.getLogger(__name__)

def save_image_from_base64(base64_image: str, file_path: str):
    """Сохраняет изображение из Base64 в файл."""
    try:
        with open(file_path, "wb") as file:
            file.write(base64.b64decode(base64_image))
        logger.info(f"Изображение сохранено в {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения: {e}")
        raise


def add_date_to_image(image_path: str, date_text: str):
    """Добавляет дату на изображение."""
    try:
        font_path = os.path.join(FONTS_PATH, "Roboto-Regular.ttf")
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Шрифт '{font_path}' не найден.")

        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        font_size = int(min(img.size) * 0.05)
        font = ImageFont.truetype(font_path, font_size)

        text_position = (img.size[0] - font_size * len(date_text) - 10, img.size[1] - font_size - 10)
        text_color = (255, 255, 255)
        shadow_color = (0, 0, 0)
        shadow_offset = 2

        draw.text(
            (text_position[0] + shadow_offset, text_position[1] + shadow_offset),
            date_text,
            font=font,
            fill=shadow_color,
        )
        draw.text(text_position, date_text, font=font, fill=text_color)
        img.save(image_path)
        logger.info(f"Дата '{date_text}' добавлена на изображение {image_path}")
    except Exception as e:
        logger.error(f"Ошибка при добавлении даты на изображение: {e}")
        raise

def create_image_path(prefix: str = "story") -> str:
    """
    Создает путь для сохранения изображения в формате: storage/images/{year}/{month}/{file_name}.
    :param prefix: Префикс имени файла.
    :return: Полный путь к файлу.
    """
    current_date = datetime.datetime.now()
    year = current_date.strftime("%Y")
    month = current_date.strftime("%m")
    file_name = f"{prefix}_{current_date.strftime('%Y%m%d_%H%M%S')}.png"

    directory = os.path.join(IMAGES_PATH, year, month)
    os.makedirs(directory, exist_ok=True)

    return os.path.join(directory, file_name)
