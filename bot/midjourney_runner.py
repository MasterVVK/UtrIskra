import asyncio
import os
from PIL import Image
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, IMAGES_PATH
from aiogram import Bot
from aiogram.types import FSInputFile
from services.midjourney_service import MidjourneyService
import logging
import requests

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_image(image_url: str, file_path: str):
    """Загрузка изображения из URL."""
    response = requests.get(image_url)
    response.raise_for_status()
    with open(file_path, "wb") as file:
        file.write(response.content)
    logger.info(f"Изображение загружено и сохранено в {file_path}")

def crop_image(grid_path: str, output_path: str, position: int):
    """
    Вырезает одно изображение из сетки 2x2.
    :param grid_path: Путь к исходной сетке изображений.
    :param output_path: Путь для сохранения вырезанного изображения.
    :param position: Позиция (1-4) изображения в сетке.
    """
    with Image.open(grid_path) as img:
        width, height = img.size
        cell_width, cell_height = width // 2, height // 2

        # Определяем координаты для вырезания
        positions = {
            1: (0, 0, cell_width, cell_height),  # Верхний левый
            2: (cell_width, 0, width, cell_height),  # Верхний правый
            3: (0, cell_height, cell_width, height),  # Нижний левый
            4: (cell_width, cell_height, width, height),  # Нижний правый
        }

        if position not in positions:
            raise ValueError("Позиция должна быть от 1 до 4.")

        cropped_img = img.crop(positions[position])
        cropped_img.save(output_path)
        logger.info(f"Изображение вырезано и сохранено в {output_path}")

async def send_midjourney_cropped_image():
    """Генерация, вырезание и отправка изображения в Telegram с использованием Midjourney API."""
    bot = Bot(token=TELEGRAM_TOKEN)
    midjourney_service = MidjourneyService()

    try:
        prompt = "A dreamy landscape with mountains and a starry sky"
        logger.info(f"Отправка запроса Imagine с промптом: {prompt}")
        imagine_task = midjourney_service.create_imagine_task(prompt, aspect_ratio="9:16")
        task_id = imagine_task["task_id"]

        logger.info(f"Ожидание завершения задачи Imagine {task_id}...")
        imagine_result = midjourney_service.wait_for_task_completion(task_id)

        grid_image_url = imagine_result["output"]["image_url"]
        if not grid_image_url:
            raise ValueError("Не удалось получить URL сетки изображений из задачи Imagine")

        # Скачивание сетки изображений
        grid_file_name = f"midjourney_grid_{task_id}.png"
        grid_file_path = os.path.join(IMAGES_PATH, grid_file_name)
        download_image(grid_image_url, grid_file_path)

        # Вырезание первого изображения (например, верхнего левого)
        cropped_file_name = f"midjourney_cropped_{task_id}.png"
        cropped_file_path = os.path.join(IMAGES_PATH, cropped_file_name)
        crop_image(grid_file_path, cropped_file_path, position=1)

        # Отправка вырезанного изображения в Telegram
        logger.info("Отправка вырезанного изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(cropped_file_path))
        logger.info("Изображение успешно отправлено!")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_midjourney_cropped_image())
