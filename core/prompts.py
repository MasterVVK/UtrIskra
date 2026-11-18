"""Промпты задач в SQLite (таблица job_prompts) с версионированием.

Промпт привязан к ключу задачи. Каждое сохранение — новая версия (INSERT),
актуальная — последняя. Плейсхолдеры рендерятся при запуске и только
в user-части: {current_date}, {random_theme}, {random_category}, {random_seed}.
"""
import datetime
import logging
import os
import random
import sqlite3

from utils.database import DB_PATH

logger = logging.getLogger(__name__)


def initialize():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_key TEXT NOT NULL,
                system_prompt TEXT NOT NULL DEFAULT '',
                user_prompt TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_prompts_key "
                     "ON job_prompts(job_key, id)")


def get_prompt(job_key: str):
    """Актуальная версия промпта задачи или None.

    id — id строки job_prompts: по нему пакетная заготовка (core/prompt_batches.py)
    узнаёт, что промпт с момента заготовки не меняли.
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, system_prompt, user_prompt, updated_at, "
            "(SELECT COUNT(*) FROM job_prompts WHERE job_key = ?) "
            "FROM job_prompts WHERE job_key = ? ORDER BY id DESC LIMIT 1",
            (job_key, job_key)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "system": row[1], "user": row[2],
            "updated_at": row[3], "version": row[4]}


def save_prompt(job_key: str, system_prompt: str, user_prompt: str) -> bool:
    """Сохраняет новую версию; возвращает False, если текст не изменился."""
    current = get_prompt(job_key)
    if current and current["system"] == system_prompt and current["user"] == user_prompt:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO job_prompts (job_key, system_prompt, user_prompt, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (job_key, system_prompt, user_prompt,
             datetime.datetime.now().isoformat(timespec="seconds")))
    logger.info("Промпт задачи «%s» сохранён (новая версия)", job_key)
    return True


def render_user_prompt(user_prompt: str, max_theme: int = 10, max_category: int = 14,
                       now: datetime.datetime = None) -> str:
    """Подставляет плейсхолдеры в user-часть промпта.

    now — момент, для которого рендерится {current_date}. Пакетная заготовка
    готовится за часы до запуска и должна нести дату запуска, а не отправки.
    """
    current_date = (now or datetime.datetime.now()).strftime("%d %B %Y")
    random_theme = str(random.randint(1, max(1, int(max_theme))))
    random_category = str(random.randint(1, max(1, int(max_category))))
    random_seed = str(random.randint(1, 999_999))
    rendered = (user_prompt
                .replace("{current_date}", current_date)
                .replace("{random_theme}", random_theme)
                .replace("{random_category}", random_category)
                .replace("{random_seed}", random_seed))
    logger.info("Промпт отрендерен: random_theme=%s, random_category=%s, random_seed=%s",
                random_theme, random_category, random_seed)
    return rendered


def parse_prompt_file(path: str) -> tuple:
    """Разбирает файл старого формата с маркерами SYSTEM/USER."""
    with open(path, encoding="utf-8") as file:
        content = file.read()
    system_prompt = content.split("---SYSTEM_PROMPT---")[1] \
                           .split("---END_SYSTEM_PROMPT---")[0].strip()
    user_prompt = content.split("---USER_PROMPT---")[1] \
                         .split("---END_USER_PROMPT---")[0].strip()
    return system_prompt, user_prompt


def migrate_from_files():
    """Разовый импорт промпт-файлов старого формата в БД (идемпотентно).

    Работает только там, где каталог PROMPTS_DIR ещё существует (старые
    развёртывания). В свежей установке промпты задаются в настройках задачи.
    """
    from config import PROMPTS_DIR
    from core import jobs as jobs_store

    if not PROMPTS_DIR or not os.path.isdir(PROMPTS_DIR):
        return
    imported = 0
    for key, job in jobs_store.load_jobs().items():
        if not job.get("prompt_file"):
            continue
        if get_prompt(key) is not None:
            continue
        path = os.path.join(PROMPTS_DIR, job["prompt_file"])
        try:
            system_prompt, user_prompt = parse_prompt_file(path)
        except Exception as exc:
            logger.warning("Промпт задачи «%s» не импортирован из %s: %s",
                           key, job["prompt_file"], exc)
            continue
        save_prompt(key, system_prompt, user_prompt)
        imported += 1
    if imported:
        logger.info("Импортировано промптов из файлов в БД: %d", imported)
