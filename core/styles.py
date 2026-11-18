"""Каталог стилей и выбор стиля и темы запуска с памятью повторов.

Каталог — data/styles.json: стили мирового искусства с видимыми признаками
(собран заранее через Claude Opus, см. docs/styles.md). Стиль запуска выбирает код,
а не LLM: на просьбу «выбери случайно» модель каждый раз выбирала бы одно и то же.

Плейсхолдеры user-части промпта (рендер — core/prompts.render_user_prompt):
  {random_style} — стиль из каталога, подходящий задаче (llm.styles в jobs.json);
  {random_theme} — номер темы; у задачи с llm.styles — без повтора недавних тем.

Память — таблица render_usage в БД промптов: что и когда выпадало задаче. Запись
делается при рендере (в том числе для заготовки, которая потом может не пригодиться:
такой стиль просто пропускает свою очередь). Любой сбой памяти не мешает запуску:
выбор идёт без неё, в журнал — предупреждение.

Настройки задачи — jobs.json, llm.styles:
  suits          — темы каталога, хотя бы одна из которых должна быть у стиля
                   (architecture, landscape, nature, objects, people, crowd, story,
                   festival, north); пусто — любые;
  min_figurative — 0 абстракция, 1 стилизация, 2 изобразительный (по умолчанию 1);
  min_fame       — 1 узкий специалист … 3 общеизвестный (по умолчанию 1);
  text           — стили, неотделимые от надписей: "inscription" (надпись нужна —
                   стиль помечается [надпись]), "graphics" (берётся только графика —
                   так и сказано в строке стиля), "exclude" (не выбирать). По умолчанию
                   "graphics";
  repeat_days    — сколько дней стиль не повторяется у этой задачи (по умолчанию 365);
  global_days    — сколько дней стиль не повторяется ни у одной задачи (3);
  section_runs   — сколько последних запусков задачи не повторяется раздел каталога
                   (например, «японская гравюра» два дня подряд) (3);
  theme_runs     — сколько последних тем задачи не повторяется (по умолчанию
                   половина max_theme, но не больше 25).
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import random
import sqlite3
import threading

from utils.database import DB_PATH

logger = logging.getLogger(__name__)

CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "styles.json")
DEFAULTS = {"suits": [], "min_figurative": 1, "min_fame": 1, "text": "graphics",
            "repeat_days": 365, "global_days": 3, "section_runs": 3}
MAX_THEME_RUNS = 25

_lock = threading.Lock()
_cache = {"mtime": None, "data": None}


def load_catalog() -> list:
    """Каталог (с кэшем по mtime). Нет файла или он битый — пустой список."""
    with _lock:
        try:
            mtime = os.path.getmtime(CATALOG_PATH)
            if _cache["mtime"] != mtime:
                with open(CATALOG_PATH, encoding="utf-8") as file:
                    data = json.load(file)
                _cache.update(mtime=mtime, data=data["styles"])
            return _cache["data"]
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("Каталог стилей %s не прочитан: %s", CATALOG_PATH, exc)
            return []


def settings(config: dict | None) -> dict:
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in (config or {}).items() if v is not None})
    return merged


def eligible(catalog: list, config: dict) -> list:
    """Стили каталога, подходящие задаче."""
    cfg = settings(config)
    suits = set(cfg["suits"] or [])
    result = []
    for style in catalog:
        if suits and not suits & set(style.get("suits") or []):
            continue
        if int(style.get("figurative", 2)) < int(cfg["min_figurative"]):
            continue
        if int(style.get("fame", 1)) < int(cfg["min_fame"]):
            continue
        if style.get("text") and cfg["text"] == "exclude":
            continue
        result.append(style)
    return result


# --- память ---------------------------------------------------------------------

def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS render_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            section TEXT NOT NULL DEFAULT '',
            rendered_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_render_usage "
                 "ON render_usage(kind, job_key, rendered_at)")
    return conn


def _iso(moment: datetime.datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _record(job_key: str, kind: str, value: str, section: str, now: datetime.datetime):
    try:
        with _connect() as conn:
            conn.execute("INSERT INTO render_usage (job_key, kind, value, section, rendered_at) "
                         "VALUES (?, ?, ?, ?, ?)", (job_key, kind, value, section, _iso(now)))
    except sqlite3.Error as exc:
        logger.warning("Память стилей: не записано (%s «%s» у «%s»): %s", kind, value, job_key, exc)


def _recent(sql: str, args: tuple) -> list:
    try:
        with _connect() as conn:
            return conn.execute(sql, args).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Память стилей не прочитана: %s — выбор без неё", exc)
        return []


# --- выбор ----------------------------------------------------------------------

def _naive(now) -> datetime.datetime:
    now = now or datetime.datetime.now()
    # Время в памяти — локальное время сервера без зоны, как в остальном журнале.
    return now.astimezone().replace(tzinfo=None) if now.tzinfo else now


def choose_style(job_key: str | None, config: dict | None, now=None, rng=random) -> dict | None:
    """Стиль запуска: случайно среди подходящих задаче, кроме недавних. None — каталог пуст."""
    now = _naive(now)
    cfg = settings(config)
    pool = eligible(load_catalog(), cfg)
    if not pool:
        return None
    if job_key is None:
        return rng.choice(pool)
    since_job = _iso(now - datetime.timedelta(days=int(cfg["repeat_days"])))
    since_all = _iso(now - datetime.timedelta(days=int(cfg["global_days"])))
    # Порядок «последних запусков» — порядок записи (id): у заготовки rendered_at — время
    # будущего запуска, и по нему недавние и будущие записи перемешались бы.
    mine = _recent("SELECT value, section FROM render_usage WHERE kind='style' AND job_key=? "
                   "AND rendered_at>=? ORDER BY id DESC", (job_key, since_job))
    everyone = {row[0] for row in _recent(
        "SELECT value FROM render_usage WHERE kind='style' AND rendered_at>=?", (since_all,))}
    used = {row[0] for row in mine}
    last_sections = {row[1] for row in mine[:int(cfg["section_runs"])] if row[1]}

    # От строгого к мягкому: без недавних стилей, разделов и чужих стилей этих дней →
    # без правила разделов → без правила «чужих» → давно не выпадавший у задачи.
    attempts = (
        [s for s in pool if s["id"] not in used | everyone and s.get("section") not in last_sections],
        [s for s in pool if s["id"] not in used | everyone],
        [s for s in pool if s["id"] not in used],
    )
    for candidates in attempts:
        if candidates:
            style = rng.choice(candidates)
            break
    else:
        order = {value: n for n, (value, _) in enumerate(mine)}   # 0 — самый свежий
        oldest = max(order.get(s["id"], -1) for s in pool)
        style = rng.choice([s for s in pool if order.get(s["id"], -1) == oldest])
    _record(job_key, "style", style["id"], style.get("section", ""), now)
    return style


def format_style(style: dict, config: dict | None) -> str:
    """Строка стиля для промпта: имя, техника, место и время, видимые признаки."""
    cfg = settings(config)
    where = ", ".join(x for x in (style.get("region"), style.get("era")) if x)
    head = style["name"]
    if style.get("medium") or where:
        head += f" ({'; '.join(x for x in (style.get('medium'), where) if x)})"
    line = f"{head} — {style['features']}"
    if style.get("note"):
        # Оговорки каталога: «не воспроизводить персонажей франшизы», «фей — одетыми» и т. п.
        line += f" (Caution: {style['note'].rstrip('.')}.)"
    if style.get("text"):
        if cfg["text"] == "inscription":
            line += " [надпись]"
        else:
            line += " (стиль связан с надписями — бери только его графику, без букв)"
    return line


def choose_theme(job_key: str | None, max_theme: int, runs: int | None = None,
                 now=None, rng=random) -> int:
    """Номер темы 1..max_theme, кроме тем последних runs запусков задачи."""
    max_theme = max(1, int(max_theme))
    if job_key is None or max_theme < 3:
        return rng.randint(1, max_theme)
    now = _naive(now)
    runs = min(max_theme // 2, MAX_THEME_RUNS) if runs is None else int(runs)
    recent = _recent("SELECT value FROM render_usage WHERE kind='theme' AND job_key=? "
                     "ORDER BY id DESC LIMIT ?", (job_key, max(runs, 0)))
    used = {row[0] for row in recent}
    free = [n for n in range(1, max_theme + 1) if str(n) not in used] or list(range(1, max_theme + 1))
    theme = rng.choice(free)
    _record(job_key, "theme", str(theme), "", now)
    return theme
