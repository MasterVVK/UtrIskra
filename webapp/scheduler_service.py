"""APScheduler-обёртка: cron-задачи генераторов, управляемые из интерфейса."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core import prompt_batches
from webapp import schedule_store
from webapp.registry import get_generators

logger = logging.getLogger(__name__)

# Служебное задание: тик пакетной заготовки промптов (core/prompt_batches.py).
# Имя заведомо не совпадает ни с одним ключом задачи из jobs.json.
BATCH_TICK_ID = "__prompt_batches_tick__"
BATCH_TICK_MINUTES = 5
# Проверка триггера вечерней заготовки (pregen): раз в минуту, без сети, если
# триггера нет. Сама заготовка идёт в своём потоке (prompt_batches.pregen_check).
PREGEN_CHECK_ID = "__prompt_pregen_check__"
SERVICE_JOB_IDS = (BATCH_TICK_ID, PREGEN_CHECK_ID)


class _QuietBatchTick(logging.Filter):
    """APScheduler пишет две INFO-строки на каждое срабатывание задания. Для тика
    раз в 5 минут это ~600 строк в сутки, под которыми в app.log (страница
    «Логи») утонули бы запуски задач. Предупреждения и ошибки тика остаются."""

    def filter(self, record):
        message = record.getMessage()
        return record.levelno > logging.INFO or not any(i in message for i in SERVICE_JOB_IDS)


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
        # Тик регистрируется всегда: флаг batch у LLM-инстанса переключается
        # в панели на ходу, а без него тик ничего не отправляет и в сеть не ходит.
        # misfire_grace_time щедрый — опоздавший тик лучше выполнить, чем пропустить.
        self.scheduler.add_job(self._batch_tick, IntervalTrigger(minutes=BATCH_TICK_MINUTES),
                               id=BATCH_TICK_ID, name=BATCH_TICK_ID, replace_existing=True,
                               max_instances=1, coalesce=True, misfire_grace_time=120)
        self.scheduler.add_job(self._pregen_check, IntervalTrigger(minutes=1),
                               id=PREGEN_CHECK_ID, name=PREGEN_CHECK_ID, replace_existing=True,
                               max_instances=1, coalesce=True, misfire_grace_time=60)
        logging.getLogger("apscheduler.executors.default").addFilter(_QuietBatchTick())
        self.scheduler.start()
        enabled = [job.id for job in self.scheduler.get_jobs() if job.id not in SERVICE_JOB_IDS]
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

    async def _batch_tick(self):
        # Тик синхронно ходит в сеть (Anthropic) и на диск — только в потоке:
        # в event loop панели он задержал бы cron-задания, а у них допуск
        # опоздания 1 секунда, после чего APScheduler запуск пропускает.
        try:
            await asyncio.to_thread(prompt_batches.tick)
        except asyncio.CancelledError:
            # Сервис останавливают посреди тика. Поток доработает сам (состояние
            # он пишет атомарно), а отмену гасим: иначе APScheduler записал бы
            # её в журнал как ошибку задания с трейсбеком.
            logger.info("Тик пакетной заготовки промптов прерван остановкой сервиса")
        except Exception as exc:  # tick() сам ничего не бросает; это страховка
            logger.warning("Тик пакетной заготовки промптов не выполнен: %s", exc)

    async def _pregen_check(self):
        try:
            await asyncio.to_thread(prompt_batches.pregen_check)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pregen_check сам ничего не бросает; это страховка
            logger.warning("Проверка вечерней заготовки не выполнена: %s", exc)

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
