import asyncio
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
    Генерация и отправка сторис в Telegram-группу.
    """
    bot = Bot(token=TELEGRAM_TOKEN)
    gemini_service = GeminiService()
    stability_service = StabilityService()

    try:
        # Генерация текстового промпта
        topic = "закат над морем"  # Тема по умолчанию, можно менять
        logger.info("Генерация описания изображения через Gemini Pro...")
        prompt = gemini_service.generate_prompt(
            system_prompt="Создай описание изображения. Используй только текст",
            user_prompt=f"Создай описание изображения на тему '{topic}'. Описание должно быть на английском языке."
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
            caption=f"Новая история на тему: {topic} 🌟"
        )
        logger.info("Изображение успешно отправлено!")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_daily_story())
