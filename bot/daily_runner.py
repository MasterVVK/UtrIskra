import asyncio
import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from config import TELEGRAM_TOKEN, TARGET_CHAT_ID
from services.gemini_service import GeminiService
from services.stability_service import StabilityService
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_daily_story():
    """
    Генерация и отправка вдохновляющей картинки в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        # Получение текущей даты
        current_date = datetime.datetime.now().strftime("%d %B %Y")  # Формат: 20 December 2024

        # Генерация текстового промпта
        logger.info("Генерация описания изображения через Gemini Pro...")
        prompt = gemini_service.generate_prompt(
            system_prompt="Создай вдохновляющий текст для генерации картинки. Используй только текст. Описание должно быть на английском языке.",
            user_prompt=(
                f"Сегодня {current_date}.\n"
                "Найди историческое событие в России, связанное с этой датой, и используй его для создания вдохновляющего текста. Используй космическую или вселенскую тематику "
                "На основе этого текста составь запрос для создания изображения, который передаст атмосферу этого события. "
                "Запрос должен быть на английском языке."
            )
        )
        logger.info(f"Сгенерированный промпт: {prompt}")

        # Генерация изображения
        logger.info("Генерация изображения через Stability AI...")
        image_content = await stability_service.generate_image(prompt)

        # Сохранение изображения
        image_path = "daily_story.png"
        with open(image_path, "wb") as file:
            file.write(image_content)
        logger.info(f"Изображение сохранено в {image_path}")

        # Отправка изображения в Telegram
        logger.info("Отправка изображения в Telegram-группу...")
        await bot.send_photo(
            chat_id=TARGET_CHAT_ID,
            photo=FSInputFile(image_path),
            caption=f"Вдохновляющее изображение дня, связанное с историей {current_date} 🌟"
        )
        logger.info("Изображение успешно отправлено!")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_daily_story())
