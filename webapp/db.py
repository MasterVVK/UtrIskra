"""Чтение базы daily_images для веб-интерфейса."""
import datetime
import os
import sqlite3

from config import IMAGES_PATH
from utils.database import DB_PATH
from webapp.registry import get_generator, generator_for_filename

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _absolute_path(image_path):
    return image_path if os.path.isabs(image_path) else os.path.join(PROJECT_ROOT, image_path)


def _media_url(image_path):
    relative = os.path.relpath(_absolute_path(image_path), IMAGES_PATH)
    if relative.startswith(".."):
        return None
    return "/media/" + relative.replace(os.sep, "/")


def _enrich(row):
    record = dict(row)
    filename = os.path.basename(record["image_path"])
    generator = generator_for_filename(filename)
    record["filename"] = filename
    record["generator_key"] = generator.key if generator else None
    record["generator_title"] = generator.title if generator else "Неизвестный"
    record["media_url"] = _media_url(record["image_path"])
    record["is_video"] = filename.lower().endswith(".mp4")
    record["file_exists"] = os.path.exists(_absolute_path(record["image_path"]))
    return record


def _generator_filter(generator_key):
    """WHERE-условие по префиксам файлов генератора ('_' в LIKE экранируется)."""
    generator = get_generator(generator_key)
    if generator is None:
        return None, []
    clauses, params = [], []
    for prefix in generator.prefixes:
        escaped = prefix.replace("_", r"\_")
        clauses.append(r"image_path LIKE ? ESCAPE '\'")
        params.append(f"%/{escaped}\\_%")
    return "(" + " OR ".join(clauses) + ")", params


def fetch_records(page=1, per_page=20, generator_key=None, search=None):
    """Возвращает (записи, всего) с фильтрами по генератору и тексту промпта."""
    where, params = [], []
    if generator_key:
        clause, clause_params = _generator_filter(generator_key)
        if clause:
            where.append(clause)
            params.extend(clause_params)
    if search:
        where.append("(generated_prompt LIKE ? OR user_prompt LIKE ?)")
        params.extend([f"%{search}%"] * 2)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with _connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM daily_images{where_sql}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM daily_images{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, per_page, (page - 1) * per_page]).fetchall()
    return [_enrich(row) for row in rows], total


def fetch_record(record_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM daily_images WHERE id = ?", (record_id,)).fetchone()
    return _enrich(row) if row else None


def stats():
    today = datetime.date.today().isoformat()
    with _connect() as connection:
        total = connection.execute("SELECT COUNT(*) FROM daily_images").fetchone()[0]
        today_count = connection.execute(
            "SELECT COUNT(*) FROM daily_images WHERE date = ?", (today,)).fetchone()[0]
        last = connection.execute(
            "SELECT date FROM daily_images ORDER BY id DESC LIMIT 1").fetchone()
    return {"total": total, "today": today_count, "last_date": last["date"] if last else None}
