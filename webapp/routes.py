"""Маршруты веб-приложения: HTML-страницы и JSON API."""
import asyncio
import datetime
import json
import math
import os
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from core import app_settings
from core import jobs as jobs_store
from core import prompts as prompts_store
from core import providers_store
from core.publisher import debug_configured
from providers.image.base import build_image_provider
from providers.llm.base import build_llm_provider
from webapp import db, registry, schedule_store, state
from webapp.task_manager import STATUS_TITLES, TRIGGER_TITLES

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

GALLERY_PER_PAGE = 24
HISTORY_PER_PAGE = 20


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _generator_status(generator, entry):
    next_run = state.scheduler_service.next_run(generator.key)
    return {
        "key": generator.key,
        "title": generator.title,
        "media": generator.media,
        "note": generator.note,
        "pipeline": generator.pipeline,
        "enabled": entry["enabled"],
        "hour": entry["hour"],
        "minute": entry["minute"],
        "debug": generator.debug,
        "running": state.task_manager.is_running(generator.key),
        "next_run": next_run.isoformat(timespec="seconds") if next_run else None,
        "last_run": state.task_manager.last_run_for(generator.key),
    }


def _status_payload():
    schedule = schedule_store.load_schedule()
    generators = [_generator_status(g, schedule.get(g.key, {
        "enabled": False, "hour": g.default_hour, "minute": g.default_minute,
    })) for g in registry.get_generators() if not g.archived]
    return {
        "server_now": _now_iso(),
        "generators": generators,
        "recent_runs": state.task_manager.recent(8),
        "running_count": sum(1 for g in generators if g["running"]),
        "enabled_count": sum(1 for g in generators if g["enabled"]),
        "debug_publish": app_settings.debug_publish_enabled(),
        "debug_configured": debug_configured(),
    }


def _page_url(base, page, generator="", q=""):
    params = {}
    if generator:
        params["generator"] = generator
    if q:
        params["q"] = q
    if page > 1:
        params["page"] = page
    return base + ("?" + urllib.parse.urlencode(params) if params else "")


# ------------------------------------------------------------------- страницы

RU_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    today = datetime.date.today()
    recent_images, _ = db.fetch_records(page=1, per_page=10)
    return templates.TemplateResponse(request, "dashboard.html", {
        "nav": "dashboard",
        "status": _status_payload(),
        "stats": db.stats(),
        "today_human": f"{today.day} {RU_MONTHS[today.month - 1]}",
        "recent_images": [r for r in recent_images if r["media_url"] and r["file_exists"]],
        "archived": [g for g in registry.get_generators() if g.archived],
    })


@router.get("/gallery", response_class=HTMLResponse)
def gallery(request: Request, generator: str = "", page: int = 1):
    page = max(page, 1)
    records, total = db.fetch_records(page=page, per_page=GALLERY_PER_PAGE,
                                      generator_key=generator or None)
    pages = max(1, math.ceil(total / GALLERY_PER_PAGE))
    return templates.TemplateResponse(request, "gallery.html", {
        "nav": "gallery",
        "records": records, "total": total, "page": page, "pages": pages,
        "generator": generator, "generators": registry.get_generators(),
        "prev_url": _page_url("/gallery", page - 1, generator) if page > 1 else None,
        "next_url": _page_url("/gallery", page + 1, generator) if page < pages else None,
    })


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, generator: str = "", q: str = "", page: int = 1):
    page = max(page, 1)
    records, total = db.fetch_records(page=page, per_page=HISTORY_PER_PAGE,
                                      generator_key=generator or None, search=q or None)
    pages = max(1, math.ceil(total / HISTORY_PER_PAGE))
    return templates.TemplateResponse(request, "history.html", {
        "nav": "history",
        "records": records, "total": total, "page": page, "pages": pages,
        "generator": generator, "q": q, "generators": registry.get_generators(),
        "prev_url": _page_url("/history", page - 1, generator, q) if page > 1 else None,
        "next_url": _page_url("/history", page + 1, generator, q) if page < pages else None,
    })


@router.get("/history/{record_id}", response_class=HTMLResponse)
def history_detail(request: Request, record_id: int):
    record = db.fetch_record(record_id)
    if record is None:
        raise HTTPException(404, "Запись не найдена")
    return templates.TemplateResponse(request, "history_detail.html", {
        "nav": "history", "record": record,
    })


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request):
    return templates.TemplateResponse(request, "runs.html", {
        "nav": "runs",
        "runs": state.task_manager.recent(200),
        "trigger_titles": TRIGGER_TITLES,
        "status_titles": STATUS_TITLES,
    })


@router.get("/providers", response_class=HTMLResponse)
def providers_page(request: Request):
    data = providers_store.load_providers()

    def rows(kind, factory):
        result = []
        for name, config in data[kind].items():
            try:
                describe = factory(name, config).describe()
            except Exception as exc:
                describe = f"ошибка конфига: {exc}"
            result.append({"name": name, "type": config.get("type", "?"),
                           "describe": describe,
                           "config_json": json.dumps(config, ensure_ascii=False, indent=2)})
        return result

    return templates.TemplateResponse(request, "providers.html", {
        "nav": "providers",
        "llm_rows": rows("llm", build_llm_provider),
        "image_rows": rows("image", build_image_provider),
        "llm_chain": data.get("llm_chain", []),
    })


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, job: str = ""):
    return templates.TemplateResponse(request, "logs.html", {
        "nav": "logs",
        "generators": registry.get_generators(),
        "job": job if registry.get_generator(job) else "",
    })


@router.get("/jobs/{key}", response_class=HTMLResponse)
def job_settings(request: Request, key: str):
    try:
        job = jobs_store.get_job(key)
    except KeyError:
        raise HTTPException(404, "Задача не найдена")
    data = providers_store.load_providers()
    image_fields = []
    if job.get("pipeline") == "image":
        provider_name = job["image"]["provider"]
        try:
            provider = build_image_provider(provider_name,
                                            providers_store.get_image_config(provider_name))
            current = provider.apply_defaults(job["image"].get("params", {}))
            for spec in provider.param_schema:
                image_fields.append({**spec, "value": current.get(spec["key"],
                                                                  spec.get("default"))})
        except Exception as exc:
            image_fields = []
            job = dict(job, note=f"Провайдер «{provider_name}» не собрался: {exc}")
    prompt = prompts_store.get_prompt(key) if job.get("pipeline") == "image" else None
    return templates.TemplateResponse(request, "job_settings.html", {
        "nav": "dashboard", "key": key, "job": job,
        "image_fields": image_fields,
        "prompt": prompt,
        "llm_names": list(data["llm"].keys()),
        "image_names": list(data["image"].keys()),
        "llm_chain": data.get("llm_chain", []),
    })


# ------------------------------------------------------------- API: статусы

@router.get("/api/status")
async def api_status():
    return _status_payload()


@router.post("/api/run/{key}", status_code=202)
async def api_run(key: str):
    generator = registry.get_generator(key)
    if generator is None:
        raise HTTPException(404, f"Неизвестный генератор: {key}")
    if generator.archived:
        raise HTTPException(409, f"«{generator.title}» в архиве — сначала верните из архива")
    try:
        run_id = state.task_manager.start(key, trigger="manual")
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"ok": True, "run_id": run_id}


class ScheduleUpdate(BaseModel):
    enabled: bool
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


@router.post("/api/schedule/{key}")
async def api_schedule(key: str, update: ScheduleUpdate):
    if registry.get_generator(key) is None:
        raise HTTPException(404, f"Неизвестный генератор: {key}")
    entry = state.scheduler_service.apply(key, update.enabled, update.hour, update.minute)
    next_run = state.scheduler_service.next_run(key)
    return {"ok": True, "entry": entry,
            "next_run": next_run.isoformat(timespec="seconds") if next_run else None}


class DebugUpdate(BaseModel):
    enabled: bool


@router.post("/api/debug")
async def api_debug(update: DebugUpdate):
    if update.enabled and not debug_configured():
        raise HTTPException(400, "Заполните DEBUG_TELEGRAM_TOKEN и DEBUG_TARGET_CHAT_ID "
                                 "в .env и перезапустите сервис")
    app_settings.set_value("debug_publish", update.enabled)
    return {"ok": True, "debug_publish": update.enabled}


@router.get("/api/runs")
async def api_runs(limit: int = 50):
    return {"runs": state.task_manager.recent(min(max(limit, 1), 200))}


@router.get("/api/runs/{run_id}/logs", response_class=PlainTextResponse)
async def api_run_logs(run_id: str):
    logs = state.task_manager.get_logs(run_id)
    if logs is None:
        raise HTTPException(404, "Запуск не найден")
    return logs or "(лог пуст)"


LOG_LINE_RE = None  # компилируется лениво в _filter_log_lines
LOG_TAIL_BYTES = 512 * 1024
LOG_LEVELS = ("ERROR", "WARNING", "INFO")


def _read_log_tail():
    from webapp.app import APP_LOG_PATH
    try:
        size = os.path.getsize(APP_LOG_PATH)
        with open(APP_LOG_PATH, "rb") as file:
            if size > LOG_TAIL_BYTES:
                file.seek(size - LOG_TAIL_BYTES)
            data = file.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return []
    lines = data.splitlines()
    if len(lines) > 1 and os.path.getsize(APP_LOG_PATH) > LOG_TAIL_BYTES:
        lines = lines[1:]  # первая строка может быть обрезана посередине
    return lines


def _filter_log_lines(lines, level, query):
    """Фильтр по уровню сохраняет строки-продолжения (трейсбеки) своей записи."""
    global LOG_LINE_RE
    if LOG_LINE_RE is None:
        import re
        # два формата: "2026-07-16 13:40:00,123 LEVEL ..." (app.log)
        # и "13:40:00 LEVEL ..." (логи запусков)
        LOG_LINE_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:,\d+)? (\w+) ")
    result = []
    include_continuation = False
    for line in lines:
        match = LOG_LINE_RE.match(line)
        if match:
            include_continuation = (not level) or match.group(1) == level
            if include_continuation:
                result.append(line)
        elif include_continuation:
            result.append(line)
    if query:
        needle = query.casefold()
        result = [line for line in result if needle in line.casefold()]
    return result


@router.get("/api/logs", response_class=PlainTextResponse)
def api_logs(lines: int = 300, level: str = "", q: str = "", job: str = "", runs: int = 3):
    if level and level not in LOG_LEVELS:
        raise HTTPException(400, f"level должен быть одним из {LOG_LEVELS}")
    if job:
        if registry.get_generator(job) is None:
            raise HTTPException(404, f"Неизвестная задача: {job}")
        raw = state.task_manager.job_logs(job, run_count=min(max(runs, 1), 20))
        if not raw:
            return "(задача ещё не запускалась — журнал пуст)"
    else:
        raw = _read_log_tail()
    filtered = _filter_log_lines(raw, level, q) if (level or q) else raw
    lines = min(max(lines, 10), 2000)
    tail = filtered[-lines:]
    return "\n".join(tail) if tail else "(пусто — под фильтр ничего не попало)"


# ---------------------------------------------------------- API: провайдеры

def _provider_factory(kind):
    if kind == "llm":
        return build_llm_provider
    if kind == "image":
        return build_image_provider
    raise HTTPException(404, f"Неизвестный вид провайдера: {kind}")


class ProviderUpdate(BaseModel):
    config: dict


class ChainUpdate(BaseModel):
    chain: list


@router.post("/api/providers/llm-chain")
async def api_save_chain(update: ChainUpdate):
    try:
        providers_store.save_llm_chain(update.chain)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "chain": update.chain}


@router.post("/api/providers/{kind}/{name}")
async def api_provider_save(kind: str, name: str, update: ProviderUpdate):
    factory = _provider_factory(kind)
    data = providers_store.load_providers()
    if name not in data[kind]:
        raise HTTPException(404, f"Провайдер «{name}» не найден")
    try:
        factory(name, update.config)  # валидация типа/конфига
    except Exception as exc:
        raise HTTPException(400, f"Конфиг не принят: {exc}")
    providers_store.save_provider(kind, name, update.config)
    return {"ok": True}


@router.post("/api/providers/{kind}/{name}/health")
async def api_provider_health(kind: str, name: str):
    factory = _provider_factory(kind)
    data = providers_store.load_providers()
    config = data[kind].get(name)
    if config is None:
        raise HTTPException(404, f"Провайдер «{name}» не найден")
    try:
        provider = factory(name, config)
        if kind == "llm":
            ok, message = await asyncio.to_thread(provider.health)
        else:
            ok, message = await provider.health()
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": ok, "message": message}


# --------------------------------------------------------------- API: задачи

class ArchiveUpdate(BaseModel):
    archived: bool


@router.post("/api/jobs/{key}/archive")
async def api_job_archive(key: str, update: ArchiveUpdate):
    try:
        job = dict(jobs_store.get_job(key))
    except KeyError:
        raise HTTPException(404, "Задача не найдена")
    job["archived"] = update.archived
    jobs_store.save_job(key, job)
    if update.archived:
        # снять с расписания, время сохранить
        entry = schedule_store.load_schedule().get(key)
        if entry:
            state.scheduler_service.apply(key, False, entry["hour"], entry["minute"])
    return {"ok": True, "archived": update.archived}


class JobUpdate(BaseModel):
    title: Optional[str] = None
    prompt: Optional[dict] = None       # {"system": str, "user": str} -> новая версия в БД
    llm: Optional[dict] = None
    image: Optional[dict] = None
    watermark: Optional[dict] = None
    publish: Optional[dict] = None


@router.post("/api/jobs/{key}")
async def api_job_save(key: str, update: JobUpdate):
    try:
        job = dict(jobs_store.get_job(key))
    except KeyError:
        raise HTTPException(404, "Задача не найдена")
    if job.get("pipeline") != "image":
        raise HTTPException(400, "Настройки доступны только для задач пайплайна image")
    data = providers_store.load_providers()

    if update.title is not None and update.title.strip():
        job["title"] = update.title.strip()[:60]

    prompt_saved = False
    if update.prompt is not None:
        user_prompt = str(update.prompt.get("user", "")).strip()
        system_prompt = str(update.prompt.get("system", "")).strip()
        if not user_prompt:
            raise HTTPException(400, "Пользовательский промпт не может быть пустым")
        prompt_saved = prompts_store.save_prompt(key, system_prompt, user_prompt)

    if update.llm is not None:
        llm = dict(job.get("llm", {}))
        provider = update.llm.get("provider") or None
        if provider and provider not in data["llm"]:
            raise HTTPException(400, f"LLM-провайдер «{provider}» не найден")
        llm["provider"] = provider
        try:
            llm["temperature"] = min(max(float(update.llm.get("temperature",
                                         llm.get("temperature", 0.7))), 0.0), 2.0)
            llm["max_theme"] = min(max(int(update.llm.get("max_theme",
                                       llm.get("max_theme", 10))), 1), 1000)
            llm["max_category"] = min(max(int(update.llm.get("max_category",
                                          llm.get("max_category", 14))), 1), 100)
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректные числовые значения LLM-настроек")
        job["llm"] = llm

    if update.image is not None:
        provider_name = update.image.get("provider") or job["image"]["provider"]
        if provider_name not in data["image"]:
            raise HTTPException(400, f"Image-провайдер «{provider_name}» не найден")
        try:
            provider = build_image_provider(provider_name,
                                            providers_store.get_image_config(provider_name))
        except Exception as exc:
            raise HTTPException(400, f"Провайдер не собрался: {exc}")
        params = provider.apply_defaults(update.image.get("params", {}))
        job["image"] = {"provider": provider_name, "params": params}

    if update.watermark is not None:
        job["watermark"] = {
            "enabled": bool(update.watermark.get("enabled", True)),
            "letter": str(update.watermark.get("letter", "")).strip()[:4],
        }

    if update.publish is not None:
        chat_id = update.publish.get("chat_id")
        debug = bool(update.publish.get("debug", False))
        if debug and not debug_configured():
            raise HTTPException(400, "Для debug-публикации заполните DEBUG_TELEGRAM_TOKEN "
                                     "и DEBUG_TARGET_CHAT_ID в .env и перезапустите сервис")
        try:
            retries = min(max(int(update.publish.get("retries", 0)), 0), 10)
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректное число ретраев")
        job["publish"] = {"chat_id": (str(chat_id).strip() or None) if chat_id else None,
                          "retries": retries, "debug": debug}

    jobs_store.save_job(key, job)
    prompt = prompts_store.get_prompt(key)
    return {"ok": True, "job": job, "prompt_saved": prompt_saved,
            "prompt_version": prompt["version"] if prompt else 0}
