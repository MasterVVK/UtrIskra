import asyncio
import datetime
import os
from PIL import Image, ImageDraw, ImageFont
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID, IMAGES_PATH, FONTS_PATH
from services.midjourney_service import MidjourneyService
from services.gemini_service import GeminiService
from utils.database import initialize_database, save_to_database
import logging
import requests

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_image_path():
    """
    Создает путь для сохранения изображения в формате: storage/images/{year}/{month}/{file_name}.
    """
    current_date = datetime.datetime.now()
    year = current_date.strftime("%Y")
    month = current_date.strftime("%m")
    file_name = f"midjourney_story_{current_date.strftime('%Y%m%d_%H%M%S')}.png"

    directory = os.path.join(IMAGES_PATH, year, month)
    os.makedirs(directory, exist_ok=True)

    return os.path.join(directory, file_name)

def add_date_to_image(image_path: str, date_text: str):
    """
    Добавляет дату на изображение.
    """
    try:
        font_path = f"{FONTS_PATH}/Roboto-Regular.ttf"
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

def download_image(image_url: str, file_path: str):
    """
    Скачивает изображение из указанного URL.
    """
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        with open(file_path, "wb") as file:
            file.write(response.content)
        logger.info(f"Изображение скачано и сохранено в {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при скачивании изображения: {e}")
        raise

def crop_image(grid_path: str, output_path: str, position: int):
    """
    Вырезает одно изображение из сетки 2x2.
    :param grid_path: Путь к исходной сетке изображений.
    :param output_path: Путь для сохранения вырезанного изображения.
    :param position: Позиция (1-4) изображения в сетке.
    """
    try:
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
    except Exception as e:
        logger.error(f"Ошибка при вырезании изображения: {e}")
        raise

def generate_dynamic_prompt():
    """
    Генерирует универсальный промпт для Gemini с использованием даты и тематики.
    """
    current_date = datetime.datetime.now().strftime("%d %B %Y")
    return (
        f"Today is {current_date}.\n"
#        "Сгенерировать одну случайную жизнеутверждающую тему на основе текущей даты. "
#        "Используй светлые тона. "
        "Сгенерируй 10 различных жизнеутверждающих и вдохновляющих тем для создания иллюстраций, со своей техникой рисования."
        "Для каждой темы укажи конкретный вид (например, от первого лица, сверху, сбоку, диагонально и т. д.) "
        "Краткое описание (3–6 предложения и действия) "
        "Расширенные стилистические ориентиры (жанр, эстетика, детали оформления, цветовая палитра, техникой рисования и т.п.) "
        "Если в теме вдруг встречаются флаги, они должны быть полностью выдуманными (не связанными с реальными странами). "
        "Включить хотя бы один интересный элемент, чтобы сделать изображение более интригующим. "
        
        "Используй номер дня месяца (например, 1…31) и рассчитай индекс как (день % 10)."
        "Если результат равен 0, выбирай 10-ю тему; "
        "Если результат не равен 0, выбирай тему с номером, равным результату."
#        "Если сегодня 6 число, то пусть рисунок будет состоять из всех 10 тем. "
#        f"Выведи только выбранную тему. Не нужно выводит список тем и результат расчета. В ней должны быть:\n"
        f"Выведи только выбранную тему. Не нужно выводит список тем и результат расчета. "
#        f"Выведи выбранную тему в начале.\n"
        "Выводи для выбранной темы только текст. "
#        f"После вывода выбранной темы поставь ---\n"
        "Use text only and write in English. "

    )

async def send_midjourney_story():
    """
    Генерация и отправка вдохновляющего изображения через Midjourney API.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    midjourney_service = MidjourneyService()
    gemini_service = GeminiService()

    try:
        # Генерация текста для промпта через Gemini
        user_prompt = generate_dynamic_prompt()
        logger.info(f"Генерация текста через Gemini с промптом: {user_prompt}")
        system_prompt = (
#            "You're a professional image request creator."
            ""
        )
        generated_prompt = gemini_service.generate_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=1
        )
#        logger.info(f"Сгенерированный необрезанный промпт для Midjourney: {generated_prompt}")
        if '---' in generated_prompt:
            generated_prompt = generated_prompt.split('---')[0].strip()
        else:
            generated_prompt = generated_prompt.strip()
        logger.info(f"Сгенерированный промпт для Midjourney: {generated_prompt}")
#        exit()

        # Генерация изображения через Midjourney
        logger.info("Генерация изображения через Midjourney...")
        imagine_task = midjourney_service.create_imagine_task(generated_prompt, aspect_ratio="9:16")
        task_id = imagine_task["task_id"]

        logger.info(f"Ожидание завершения задачи Imagine {task_id}...")
        imagine_result = midjourney_service.wait_for_task_completion(task_id)

        # Скачивание необработанного изображения
        grid_image_url = imagine_result["output"]["image_url"]
        if not grid_image_url:
            raise ValueError("Не удалось получить URL сетки изображений из задачи Imagine")

        raw_image_path = create_image_path()
        logger.info("Сохранение необработанного изображения...")
        download_image(grid_image_url, raw_image_path)

        # Вырезание первого изображения
        processed_image_path = raw_image_path.replace(".png", "_processed.png")
        crop_image(raw_image_path, processed_image_path, position=1)

        # Добавление даты на обработанное изображение
        current_date_text = "M " + datetime.datetime.now().strftime("%d.%m.%Y")
        add_date_to_image(processed_image_path, current_date_text)

        # Сохранение в базу данных
        save_to_database(
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generated_prompt=generated_prompt,
            image_path=processed_image_path
        )

        # Отправка изображения в Telegram
        logger.info("Отправка изображения в Telegram...")
        await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=FSInputFile(processed_image_path))
        logger.info("Изображение успешно отправлено!")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    initialize_database()
    asyncio.run(send_midjourney_story())
