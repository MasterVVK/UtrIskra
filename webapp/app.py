"""FastAPI-приложение UtrIskra: панель управления генерацией и публикацией.

Запуск: python run_web.py (или uvicorn webapp.app:app --host 0.0.0.0 --port 8090).
Работает в один процесс: внутри живёт APScheduler, поэтому main.py и cron
для запуска раннеров больше не нужны.
"""
import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import BASE_STORAGE_PATH, IMAGES_PATH
from core import prompts as prompts_store
from utils.database import initialize_database
from webapp import routes, state

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
APP_LOG_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "app.log")

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def _setup_file_logging():
    """Дублирует логи в storage/webapp/app.log (ротация 5МБ × 3) —
    их показывает страница «Логи»; uvicorn.access не пишем (шум поллинга)."""
    os.makedirs(os.path.dirname(APP_LOG_PATH), exist_ok=True)
    handler = RotatingFileHandler(APP_LOG_PATH, maxBytes=5_000_000,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    logging.getLogger("uvicorn").addHandler(handler)


_setup_file_logging()


@asynccontextmanager
async def lifespan(_app):
    initialize_database()
    prompts_store.initialize()
    prompts_store.migrate_from_files()
    state.task_manager.install_log_handler()
    state.scheduler_service.start()
    yield
    state.scheduler_service.shutdown()


app = FastAPI(title="UtrIskra", lifespan=lifespan)

os.makedirs(IMAGES_PATH, exist_ok=True)
app.mount("/static",
          StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
          name="static")
app.mount("/media", StaticFiles(directory=IMAGES_PATH), name="media")
app.include_router(routes.router)
