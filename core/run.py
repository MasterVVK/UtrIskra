"""CLI-запуск задачи: python -m core.run <ключ задачи>

Список ключей — в storage/webapp/jobs.json (или webapp-панель, раздел «Дашборд»).
"""
import logging
import sys

from core import jobs as jobs_store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: python -m core.run <ключ задачи>")
        print("Доступные задачи:", ", ".join(jobs_store.load_jobs()))
        sys.exit(2)
    key = sys.argv[1]
    if key not in jobs_store.load_jobs():
        print(f"Задача «{key}» не найдена. Доступные:", ", ".join(jobs_store.load_jobs()))
        sys.exit(2)

    from utils.database import initialize_database
    from core.pipeline import run_job_sync

    initialize_database()
    run_job_sync(key)
