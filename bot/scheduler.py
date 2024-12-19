from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.telegram_bot import StoryBot

async def start_scheduler():
    """Запуск планировщика задач."""
    story_bot = StoryBot()
    scheduler = AsyncIOScheduler()

    # Запуск задачи раз в день в 9 утра
    scheduler.add_job(story_bot.publish_story, "cron", hour=9, minute=0)
    scheduler.start()
