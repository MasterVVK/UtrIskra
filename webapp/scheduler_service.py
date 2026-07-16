"""APScheduler-обёртка: cron-задачи генераторов, управляемые из интерфейса."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from webapp import schedule_store
from webapp.registry import get_generators

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, task_manager):
        self.task_manager = task_manager
        self.scheduler = AsyncIOScheduler()

    def start(self):
        schedule = schedule_store.load_schedule()
        for generator in get_generators():
            entry = schedule[generator.key]
            if entry["enabled"] and not generator.archived:
                self._add_job(generator.key, entry["hour"], entry["minute"])
        self.scheduler.start()
        enabled = [job.id for job in self.scheduler.get_jobs()]
        logger.info("Планировщик запущен, активных задач: %d %s", len(enabled), enabled)

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _add_job(self, key, hour, minute):
        self.scheduler.add_job(self._run, CronTrigger(hour=hour, minute=minute),
                               args=[key], id=key, replace_existing=True)

    async def _run(self, key):
        try:
            self.task_manager.start(key, trigger="schedule")
        except (KeyError, RuntimeError) as exc:
            logger.warning("Запуск %s по расписанию пропущен: %s", key, exc)

    def apply(self, key, enabled, hour, minute):
        """Сохраняет настройку и перестраивает cron-задачу генератора."""
        entry = schedule_store.set_entry(key, enabled, hour, minute)
        if self.scheduler.get_job(key):
            self.scheduler.remove_job(key)
        if entry["enabled"]:
            self._add_job(key, entry["hour"], entry["minute"])
        logger.info("Расписание %s: enabled=%s %02d:%02d",
                    key, entry["enabled"], entry["hour"], entry["minute"])
        return entry

    def next_run(self, key):
        job = self.scheduler.get_job(key) if self.scheduler.running else None
        return job.next_run_time if job else None
