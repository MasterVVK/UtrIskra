from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.daily_runner import send_daily_story
from bot.kandinsky_runner import send_kandinsky_story
from bot.midjourney_runner import send_midjourney_story
from bot.midjourney_video_runner import send_midjourney_video_story
from bot.dalle_runner import send_dalle_story
from bot.flux_runner import send_flux_story
from bot.yandex_runner import send_yandex_story
from bot.gemini_image_runner import send_gemini_image_story
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_scheduler():
    """
    Запускает планировщик задач для отправки историй.
    """
    scheduler = AsyncIOScheduler()

    # Добавление задач для каждого раннера
    scheduler.add_job(send_daily_story, "cron", hour=7, minute=0)
    scheduler.add_job(send_kandinsky_story, "cron", hour=8, minute=0)
    scheduler.add_job(send_midjourney_story, "cron", hour=9, minute=0)
    scheduler.add_job(send_dalle_story, "cron", hour=10, minute=0)
    scheduler.add_job(send_flux_story, "cron", hour=11, minute=0)
    scheduler.add_job(send_yandex_story, "cron", hour=12, minute=0)
    scheduler.add_job(send_gemini_image_story, "cron", hour=13, minute=0)
    scheduler.add_job(send_midjourney_video_story, "cron", hour=14, minute=0)


    scheduler.start()
    logger.info("Планировщик запущен.")
