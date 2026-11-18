"""Пакетная заготовка промптов через Anthropic Message Batches API.

Пакетный запрос вдвое дешевле синхронного, но ответ приходит не сразу (обычно
в пределах часа, максимум сутки). Расписание известно заранее, поэтому тексты
для ближайших запусков заказываются пакетом за пару часов, и к запуску задача
берёт готовый текст вместо синхронного вызова.

Как это устроено:
  * тик раз в 5 минут (webapp/scheduler_service.py) опрашивает отправленные
    пакеты, списывает негодные заготовки и — когда до ближайшего ещё не
    подготовленного запуска остаётся не больше batch_lead_minutes — отправляет
    ОДИН пакет на все запуски в окне [сейчас + 10 мин; сейчас + batch_horizon_minutes];
  * пайплайн (core/pipeline.py: _prepare_prompt) перед цепочкой LLM зовёт
    take_draft(): есть годная заготовка — берёт её, нет — обычная цепочка;
  * режим включён флагом "batch": true у LLM-инстанса типа anthropic и действует,
    только если этот инстанс первый в цепочке задачи. Без флага модуль ничего
    не отправляет и заготовок не выдаёт.

В заготовке хранятся уже отрендеренные system/user (со случайными числами и
датой запуска) — в историю попадает ровно то, по чему модель писала текст.

Состояние — storage/webapp/prompt_batches.json: переживает перезапуск сервиса.
С ним работают и тик панели, и поток пайплайна, и CLI из другого процесса,
поэтому блокировка двойная: threading — между потоками, flock — между процессами.

Любой сбой здесь (нет сети, ошибка API, битый файл состояния) — только
предупреждение в журнал: задача пойдёт обычной цепочкой LLM.

Вечерняя заготовка (pregen). LLM-инстанс с флагом "pregen": true (Qwen4 через
Qwen2API) пишет тексты заранее, синхронно и строго по одному запросу: его суточная
квота общая с другими клиентами сервиса и к утру выбрана, поэтому промпты на утро
заказываются вечером, сразу после сброса лимита. Момент старта задаёт файл-триггер
(pregen_trigger_file): его пишет сторона, которая видит сброс квоты; по окончании
модуль пишет pregen_done_file с итогом, и та сторона продолжает свою работу. После
первой же ошибки заготовка останавливается до следующего триггера: повторы
кулдаунят пул аккаунтов. Недописанные запуски закрывает пакет Opus.
Заготовки pregen задача берёт раньше пакетных, если инстанс есть в её цепочке.

CLI: python -m core.prompt_batches status | tick | submit <ключи...> | poll | pregen
"""
import contextlib
import datetime
import fcntl
import json
import logging
import os
import re
import sys
import threading
import time
import uuid

from apscheduler.triggers.cron import CronTrigger

from config import BASE_STORAGE_PATH
from core import jobs as jobs_store
from core import prompts as prompts_store
from core import providers_store
from providers.llm.base import build_llm_provider
from webapp import schedule_store

# имя задано явно: при запуске CLI (python -m) модуль зовётся __main__,
# а строки журнала должны выглядеть так же, как у тика панели
logger = logging.getLogger("core.prompt_batches")

STATE_PATH = os.path.join(BASE_STORAGE_PATH, "webapp", "prompt_batches.json")

# Пайплайны, берущие промпт через _prepare_prompt (best_image_video — нет).
PROMPT_PIPELINES = ("image", "midjourney_video")

DEFAULT_LEAD_MINUTES = 120      # за сколько до ближайшего запуска слать пакет
DEFAULT_HORIZON_MINUTES = 360   # на сколько вперёд набирать запуски в пакет
MIN_AHEAD_MINUTES = 10          # ближе к запуску заказывать бессмысленно: не успеет
EARLY_MARGIN_MINUTES = 30       # заготовка годна с (запуск − lead − этот запас)…
LATE_HOURS = 12                 # …и до (запуск + 12 ч): опоздавший или ручной запуск
SUBMIT_RETRY_MINUTES = 15       # пауза после неудачной отправки пакета
KEEP_DAYS = 3                   # сколько хранить отработавшие записи

LIVE = ("pending", "ready")     # заготовка ещё может пригодиться

PREGEN_HORIZON_HOURS = 14       # вечером — на все запуски до следующего утра
PREGEN_TRIGGER_MAX_AGE_HOURS = 3  # старый триггер (после простоя панели) не срабатывает

_state_lock = threading.Lock()  # короткие секции «прочитал — изменил — записал»
_tick_lock = threading.Lock()   # тик целиком, включая сетевые вызовы
_pregen_lock = threading.Lock()  # вечерняя заготовка целиком (десятки минут)


class _Busy(Exception):
    """Тик уже выполняется в другом потоке или процессе."""


# ------------------------------------------------------------------ состояние

def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _iso(moment: datetime.datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


@contextlib.contextmanager
def _exclusive(suffix: str, thread_lock: threading.Lock, blocking: bool = True):
    """Исключительная секция и между потоками, и между процессами (панель ↔ CLI)."""
    if not thread_lock.acquire(blocking=blocking):
        raise _Busy()
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH + suffix, "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise _Busy() from None
            yield  # flock снимается при закрытии файла
    finally:
        thread_lock.release()


def _well_formed(data) -> bool:
    """Все поля, на которые опирается логика, на месте, а времена — с часовым поясом."""
    try:
        return (all(_parse(d["run_at"]).tzinfo and _parse(d["created_at"]).tzinfo
                    and d["status"] and d["job"] and d["provider"]
                    and "prompt_id" in d and "batch_id" in d
                    for d in data["drafts"].values())
                and all(_parse(b["submitted_at"]).tzinfo and b["status"] and b["provider"]
                        for b in data["batches"].values())
                and isinstance(data["submit_failed_at"], dict))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _load() -> dict:
    """Читает состояние. Битый файл откладывается в сторону — работа с пустого.

    Ошибка чтения (OSError) битым файлом не считается и уходит наверх: файл,
    который не удалось прочитать, переносить нельзя — он может быть цел.
    """
    empty = {"batches": {}, "drafts": {}, "submit_failed_at": {}, "pregen": {}}
    try:
        with open(STATE_PATH, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return empty
    except ValueError as exc:  # не JSON или не UTF-8
        data, reason = None, str(exc)
    else:
        reason = "неожиданная структура"
        if isinstance(data, dict):
            for section in empty:
                data.setdefault(section, {})
    if data is None or not _well_formed(data):
        # Не чиним и не затираем: файл уходит на разбор, а заготовки из него
        # просто не будут использованы — задачи пойдут обычной цепочкой.
        aside = f"{STATE_PATH}.broken-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        with contextlib.suppress(OSError):
            os.replace(STATE_PATH, aside)
        logger.warning("Пакетная заготовка: файл состояния повреждён (%s) — отложен как %s, "
                       "начинаю с пустого", reason, aside)
        return empty
    return data


def _save(data: dict):
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp_path, STATE_PATH)


@contextlib.contextmanager
def _state():
    """Состояние под блокировкой; на диск пишется, только если изменилось."""
    with _exclusive(".lock", _state_lock):
        data = _load()
        before = json.dumps(data, sort_keys=True)
        yield data
        if json.dumps(data, sort_keys=True) != before:
            _save(data)


# ------------------------------------------------------------------- правила

def next_run(entry: dict, now: datetime.datetime) -> datetime.datetime:
    """Ближайший запуск по расписанию — тем же CronTrigger, что у планировщика
    панели, чтобы часовой пояс и переходы времени считались одинаково."""
    return CronTrigger(hour=entry["hour"], minute=entry["minute"]).get_next_fire_time(None, now)


def batch_provider(job: dict, forced: bool = False):
    """(имя, конфиг) инстанса, который готовит задаче промпты пакетом, или None.

    Это первый LLM в цепочке задачи, если он типа anthropic и у него "batch": true.
    forced (ручная отправка из CLI) флага не требует.
    """
    # та же развилка, что в core/pipeline.py: _generate_text — менять вместе
    own_provider = (job.get("llm") or {}).get("provider")
    chain = [own_provider] if own_provider else providers_store.llm_chain()
    if not chain:
        return None
    try:
        config = providers_store.get_llm_config(chain[0])
    except KeyError:
        return None
    if config.get("type") != "anthropic" or not (forced or config.get("batch")):
        return None
    return chain[0], config


def draft_providers(job: dict) -> list:
    """Имена LLM, чьи заготовки задача берёт, в порядке предпочтения.

    Сначала инстансы с "pregen": true из её цепочки (вечерняя заготовка), затем
    пакетный (batch_provider). Пусто — задача заготовками не пользуется.
    """
    own_provider = (job.get("llm") or {}).get("provider")
    chain = [own_provider] if own_provider else providers_store.llm_chain()
    names = []
    for name in chain:
        try:
            if providers_store.get_llm_config(name).get("pregen"):
                names.append(name)
        except KeyError:
            continue
    batch = batch_provider(job)
    if batch is not None and batch[0] not in names:
        names.append(batch[0])
    return names


def _window(draft: dict) -> tuple:
    """Когда заготовкой можно пользоваться: «около» планового времени запуска."""
    run_at = _parse(draft["run_at"])
    early = int(draft.get("lead_minutes", DEFAULT_LEAD_MINUTES)) + EARLY_MARGIN_MINUTES
    return (run_at - datetime.timedelta(minutes=early),
            run_at + datetime.timedelta(hours=LATE_HOURS))


def _label(draft: dict) -> str:
    return f"«{draft['job']}» на {_parse(draft['run_at']):%d.%m %H:%M}"


def _retire(draft: dict, prompt_id, now: datetime.datetime) -> bool:
    """Списывает живую заготовку, которой пользоваться уже нельзя. True — списана."""
    if now > _window(draft)[1]:
        draft["status"] = "expired"
        logger.info("Пакетная заготовка %s просрочена: не понадобилась за %d ч после "
                    "планового времени", _label(draft), LATE_HOURS)
        return True
    if draft["prompt_id"] != prompt_id:
        draft["status"] = "stale"
        logger.info("Пакетная заготовка %s отброшена: промпт задачи с тех пор изменился "
                    "(была версия #%s, сейчас #%s)", _label(draft), draft["prompt_id"], prompt_id)
        return True
    return False


def _covered(data: dict, key: str, run_at: datetime.datetime, provider_names,
             count_failed: bool = True) -> bool:
    """Есть ли на этот запуск заготовка (от любого из provider_names) или запрос."""
    for draft in data["drafts"].values():
        if draft["job"] != key:
            continue
        if draft["status"] in LIVE and draft["provider"] in provider_names:
            start, end = _window(draft)
            if start <= run_at <= end:
                return True
        # Неудачный запрос (отказ, обрыв, ошибка) на тот же запуск не повторяется:
        # обрыв по max_tokens оплачивается, и слать его снова каждые 5 минут
        # незачем — задача пойдёт обычной цепочкой.
        if count_failed and draft["status"] == "failed" and _parse(draft["run_at"]) == run_at:
            return True
    return False


# ---------------------------------------------------------------- использование

def take_draft(key: str, job: dict, prompt_row: dict, now: datetime.datetime = None):
    """Заготовка для запуска задачи «сейчас» (помечается использованной) или None.

    prompt_row — актуальный промпт задачи (prompts.get_prompt): заготовка годна,
    только если написана по этой же его версии.
    Никогда не бросает исключений: что бы ни случилось с пакетным механизмом,
    задача должна запуститься обычной цепочкой LLM.
    """
    try:
        names = draft_providers(job)
        if not names:
            return None
        return _take(key, names, prompt_row["id"], now or _now())
    except Exception as exc:
        logger.warning("Пакетная заготовка для «%s» недоступна (%s) — обычная цепочка LLM",
                       key, exc)
        return None


def _take(key: str, provider_names: list, prompt_id, now: datetime.datetime):
    def rank(draft):  # сначала предпочтительный LLM, затем ближайший запуск
        return provider_names.index(draft["provider"]), abs(_parse(draft["run_at"]) - now)

    with _state() as data:
        best = waiting = None
        for draft in data["drafts"].values():
            if draft["job"] != key or draft["status"] not in LIVE:
                continue
            if _retire(draft, prompt_id, now):
                continue
            if now < _window(draft)[0] or draft["provider"] not in provider_names:
                continue  # заготовка для другого, более позднего запуска
            if draft["status"] == "pending":
                waiting = draft
            elif best is None or rank(draft) < rank(best):
                best = draft
        if best is None:
            if waiting is not None:
                logger.info("Задача «%s»: пакетная заготовка ещё не готова (пакет %s "
                            "в обработке) — обычная цепочка LLM", key, waiting["batch_id"])
            return None
        best["status"] = "used"
        best["used_at"] = _iso(now)
        return dict(best)


# ---------------------------------------------------------------------- опрос

def poll(now: datetime.datetime = None) -> list:
    """Проверяет отправленные пакеты; завершённые разбирает в заготовки.

    Возвращает строки-сводки по каждому проверенному пакету (для CLI).
    """
    now = now or _now()
    with _state() as data:
        waiting = {batch_id: batch["provider"] for batch_id, batch in data["batches"].items()
                   if batch["status"] == "in_progress"}
    report = []
    for batch_id, provider_name in waiting.items():
        try:
            try:
                config = providers_store.get_llm_config(provider_name)
            except KeyError:
                # инстанс удалили из providers.json — спросить пакет больше нечем
                _store_results(batch_id, None, None, now,
                               f"LLM-инстанс «{provider_name}» удалён из providers.json")
                report.append(f"{batch_id}: потерян (инстанс «{provider_name}» удалён)")
                continue
            provider = build_llm_provider(provider_name, config)
            status = provider.batch_status(batch_id)
            if status["status"] == "not_found":
                _store_results(batch_id, None, None, now, "пакет не найден на стороне API")
                report.append(f"{batch_id}: не найден на стороне API")
                continue
            if status["status"] != "ended":
                report.append(f"{batch_id}: {status['status']}, "
                              f"в обработке {status['processing']}")
                continue
            results = provider.batch_results(batch_id)
        except Exception as exc:
            logger.warning("Пакет %s: опрос не удался (%s) — повторю на следующем тике",
                           batch_id, exc)
            report.append(f"{batch_id}: опрос не удался — {exc}")
            continue
        report.append(f"{batch_id}: {_store_results(batch_id, results, status['ended_at'], now)}")
    return report


def _store_results(batch_id: str, results, ended_at, now: datetime.datetime,
                   lost_reason: str = None) -> str:
    """Раскладывает результаты пакета по заготовкам (сопоставление — по custom_id)."""
    with _state() as data:
        batch = data["batches"].get(batch_id)
        if batch is None or batch["status"] != "in_progress":
            return "уже разобран"  # успел другой процесс (панель ↔ CLI)
        ready = failed = tokens_in = tokens_out = 0
        for draft in data["drafts"].values():
            # списанные (просрочка, смена промпта) результата уже не ждут
            if draft["batch_id"] != batch_id or draft["status"] != "pending":
                continue
            outcome = (results or {}).get(draft["id"]) or {}
            if outcome.get("text"):
                usage = outcome.get("usage") or {}
                draft.update(status="ready", text=outcome["text"], model=outcome.get("model"),
                             usage=usage, ready_at=_iso(now))
                ready += 1
                tokens_in += usage.get("input_tokens") or 0
                tokens_out += usage.get("output_tokens") or 0
            else:
                reason = (lost_reason or outcome.get("error")
                          or "в результатах пакета нет ответа на этот запрос")
                draft.update(status="failed", error=reason)
                failed += 1
                logger.warning("Пакет %s: заготовка %s не получена — %s; задача пойдёт "
                               "обычной цепочкой LLM", batch_id, _label(draft), reason)
        batch["status"] = "lost" if lost_reason else "ended"
        batch["ended_at"] = ended_at or _iso(now)
        minutes = (_parse(batch["ended_at"]) - _parse(batch["submitted_at"])).total_seconds() / 60
        summary = (f"готово {ready}, отказов {failed}, шёл {minutes:.0f} мин, "
                   f"токены: вход {tokens_in}, выход {tokens_out}")
        if lost_reason:
            logger.warning("Пакет %s потерян: %s", batch_id, lost_reason)
        else:
            logger.info("Пакет %s завершён: %s", batch_id, summary)
        return summary


# -------------------------------------------------------------------- отправка

def _housekeeping(now: datetime.datetime):
    """Списывает просроченные и устаревшие заготовки, удаляет старые записи."""
    with _state() as data:
        prompt_ids = {}
        for draft in data["drafts"].values():
            if draft["status"] not in LIVE:
                continue
            key = draft["job"]
            if key not in prompt_ids:
                prompt = prompts_store.get_prompt(key)
                prompt_ids[key] = prompt["id"] if prompt else None
            _retire(draft, prompt_ids[key], now)
        limit = now - datetime.timedelta(days=KEEP_DAYS)
        data["drafts"] = {draft_id: draft for draft_id, draft in data["drafts"].items()
                          if _parse(draft["created_at"]) > limit}
        data["batches"] = {batch_id: batch for batch_id, batch in data["batches"].items()
                           if _parse(batch["submitted_at"]) > limit}


def _minutes(config: dict, name: str, default: int) -> datetime.timedelta:
    try:
        return datetime.timedelta(minutes=max(1, int(config.get(name, default))))
    except (TypeError, ValueError):
        return datetime.timedelta(minutes=default)


def submit_due(now: datetime.datetime = None) -> list:
    """Отправляет пакет, если подошло время. Возвращает id отправленных пакетов.

    Пакетов больше одного, только если у задач разные batch-инстансы (свой
    провайдер у задачи): у каждого инстанса своя модель и свои lead/horizon.
    """
    now = now or _now()
    schedule = schedule_store.load_schedule()
    groups = {}
    for key, job in jobs_store.load_jobs().items():
        entry = schedule.get(key)
        if job.get("archived") or not entry or not entry["enabled"]:
            continue
        if job.get("pipeline", "image") not in PROMPT_PIPELINES:
            continue
        provider = batch_provider(job)
        if provider is None:
            continue
        name, config = provider
        groups.setdefault(name, (config, []))[1].append((key, job, next_run(entry, now)))

    sent = []
    for name, (config, runs) in groups.items():
        lead = _minutes(config, "batch_lead_minutes", DEFAULT_LEAD_MINUTES)
        horizon = _minutes(config, "batch_horizon_minutes", DEFAULT_HORIZON_MINUTES)
        earliest = now + datetime.timedelta(minutes=MIN_AHEAD_MINUTES)
        with _state() as data:
            failed_at = data["submit_failed_at"].get(name)
            todo = [(key, job, run_at) for key, job, run_at in runs
                    if earliest <= run_at <= now + horizon
                    and not _covered(data, key, run_at, draft_providers(job))]
        # ждём, пока ближайший неподготовленный запуск не окажется в пределах lead:
        # так в один пакет попадают все запуски окна, а не по одному на тик
        if not todo or min(run_at for _, _, run_at in todo) - now > lead:
            continue
        if failed_at and now - _parse(failed_at) < datetime.timedelta(minutes=SUBMIT_RETRY_MINUTES):
            continue
        batch_id = _submit(name, config, todo, now)
        if batch_id:
            sent.append(batch_id)
    return sent


def submit_forced(keys: list, now: datetime.datetime = None) -> list:
    """Ручная отправка (CLI): пакет для перечисленных задач, как будто их запуск скоро.

    Не смотрит ни на флаг batch, ни на lead/horizon. Заготовка делается на
    ближайший запуск задачи по расписанию; если расписание выключено — на «сейчас».
    Запуск, на который уже есть живая заготовка или запрос, повторно не заказывается.
    """
    now = now or _now()
    _housekeeping(now)
    schedule = schedule_store.load_schedule()
    jobs = jobs_store.load_jobs()
    groups = {}
    for key in keys:
        job = jobs.get(key)
        if job is None or job.get("pipeline", "image") not in PROMPT_PIPELINES:
            logger.warning("Задача «%s» пропущена: её нет или её пайплайн не берёт промпт у LLM", key)
            continue
        provider = batch_provider(job, forced=True)
        if provider is None:
            logger.warning("Задача «%s» пропущена: первый LLM в её цепочке — не anthropic", key)
            continue
        name, config = provider
        entry = schedule.get(key)
        run_at = next_run(entry, now) if entry and entry["enabled"] else now
        with _state() as data:
            if _covered(data, key, run_at, draft_providers(job) + [name], count_failed=False):
                logger.info("Задача «%s»: на запуск %s уже есть заготовка или запрос — "
                            "повторно не отправляю", key, f"{run_at:%d.%m %H:%M}")
                continue
        groups.setdefault(name, (config, []))[1].append((key, job, run_at))
    sent = []
    for name, (config, runs) in groups.items():
        batch_id = _submit(name, config, runs, now)
        if batch_id:
            sent.append(batch_id)
    return sent


def _submit(name: str, config: dict, runs: list, now: datetime.datetime):
    """Один пакет на перечисленные запуски; заготовки записываются ожидающими."""
    lead = _minutes(config, "batch_lead_minutes", DEFAULT_LEAD_MINUTES)
    drafts = []
    for key, job, run_at in runs:
        prompt = prompts_store.get_prompt(key)
        if prompt is None:
            continue  # промпт не задан — запуск задачи сам сообщит об этом ошибкой
        # Рендер — тот же вызов, что в core/pipeline.py: _prepare_prompt (менять
        # вместе), только дата в промпте — дата запуска, а не отправки пакета.
        llm_config = job.get("llm") or {}
        user_prompt = prompts_store.render_user_prompt(
            prompt["user"],
            max_theme=int(llm_config.get("max_theme", 10)),
            max_category=int(llm_config.get("max_category", 14)),
            now=run_at,
        )
        drafts.append({
            # он же custom_id запроса: по нему результат находит свою заготовку
            "id": f"{re.sub(r'[^A-Za-z0-9_-]', '_', key)[:40]}-{run_at:%Y%m%dT%H%M}-"
                  f"{uuid.uuid4().hex[:6]}",
            "job": key,
            "run_at": _iso(run_at),
            "status": "pending",
            "provider": name,
            "batch_id": None,
            "prompt_id": prompt["id"],
            "lead_minutes": int(lead.total_seconds() // 60),
            "system": prompt["system"],
            "user": user_prompt,
            "created_at": _iso(now),
        })
    if not drafts:
        return None
    try:
        provider = build_llm_provider(name, config)
        batch_id = provider.submit_batch([(d["id"], d["system"], d["user"]) for d in drafts])
    except Exception as exc:
        with _state() as data:
            data["submit_failed_at"][name] = _iso(now)
        logger.warning("Пакет заготовок для %s не отправлен (%s) — повтор не раньше чем через "
                       "%d мин; без заготовки задачи пойдут обычной цепочкой LLM",
                       ", ".join(d["job"] for d in drafts), exc, SUBMIT_RETRY_MINUTES)
        return None
    logger.info("Отправлен пакет %s (LLM «%s», %s): %s", batch_id, name, provider.describe(),
                ", ".join(f"{d['job']} на {_parse(d['run_at']):%d.%m %H:%M}" for d in drafts))
    with _state() as data:
        data["submit_failed_at"].pop(name, None)
        data["batches"][batch_id] = {"provider": name, "status": "in_progress",
                                     "submitted_at": _iso(now), "ended_at": None}
        for draft in drafts:
            draft["batch_id"] = batch_id
            data["drafts"][draft["id"]] = draft
    return batch_id


# ----------------------------------------------------------- вечерняя заготовка

def pregen_providers() -> list:
    """(имя, конфиг) LLM-инстансов с "pregen": true."""
    return [(name, config) for name, config in providers_store.load_providers()["llm"].items()
            if config.get("pregen")]


def _hours(config: dict, name: str, default: int) -> datetime.timedelta:
    try:
        return datetime.timedelta(hours=max(1, float(config.get(name, default))))
    except (TypeError, ValueError):
        return datetime.timedelta(hours=default)


def _pregen_runs(name: str, config: dict, now: datetime.datetime) -> list:
    """Запуски, которым инстанс name может заготовить текст: задача включена, берёт
    его заготовки, запуск в [сейчас + 10 мин; сейчас + горизонт] и ещё не закрыт."""
    schedule = schedule_store.load_schedule()
    earliest = now + datetime.timedelta(minutes=MIN_AHEAD_MINUTES)
    latest = now + _hours(config, "pregen_horizon_hours", PREGEN_HORIZON_HOURS)
    runs = []
    with _state() as data:
        for key, job in jobs_store.load_jobs().items():
            entry = schedule.get(key)
            if job.get("archived") or not entry or not entry["enabled"]:
                continue
            if job.get("pipeline", "image") not in PROMPT_PIPELINES:
                continue
            names = draft_providers(job)
            if name not in names:
                continue
            run_at = next_run(entry, now)
            if earliest <= run_at <= latest and not _covered(data, key, run_at, names):
                runs.append((key, job, run_at))
    return sorted(runs, key=lambda run: run[2])


def pregenerate(now: datetime.datetime = None) -> dict:
    """Вечерняя заготовка: по одному синхронному запросу на запуск, стоп на первой ошибке.

    Возвращает итог {started, finished, ok, failed, reason} — он же уходит в
    pregen_done_file. Исключений не бросает.
    """
    now = now or _now()
    started = time.monotonic()

    def clock():  # «сейчас» в шкале now: в тестах now задан, а запросы идут по-настоящему
        return now + datetime.timedelta(seconds=time.monotonic() - started)

    summary = {"started": _iso(now), "finished": None, "ok": 0, "failed": 0, "reason": None}
    try:
        with _exclusive(".pregen.lock", _pregen_lock, blocking=False):
            _housekeeping(now)
            for name, config in pregen_providers():
                runs = _pregen_runs(name, config, now)
                if not runs:
                    continue
                provider = build_llm_provider(name, config)
                logger.info("Вечерняя заготовка (LLM «%s»): %d запусков — %s", name, len(runs),
                            ", ".join(f"{key} на {run_at:%d.%m %H:%M}" for key, _, run_at in runs))
                for index, (key, job, run_at) in enumerate(runs):
                    if not _pregen_one(name, config, provider, key, job, run_at, summary,
                                       clock):
                        left = len(runs) - index - 1
                        summary["reason"] = summary["reason"] or "ошибка"
                        logger.warning("Вечерняя заготовка остановлена после ошибки: %s. "
                                       "Остальные %d запусков подготовит пакет Opus или "
                                       "обычная цепочка", summary["reason"], left)
                        break
                if summary["failed"]:
                    break
    except _Busy:
        summary["reason"] = "вечерняя заготовка уже идёт"
        logger.info("Вечерняя заготовка уже выполняется — пропуск")
    except Exception as exc:
        summary["reason"] = f"сбой: {exc}"
        logger.warning("Вечерняя заготовка: сбой — %s", exc)
    summary["finished"] = _iso(clock())
    return summary


def _pregen_one(name, config, provider, key, job, run_at, summary, clock) -> bool:
    """Один запрос. True — заготовка записана; False — ошибка (в summary)."""
    prompt = prompts_store.get_prompt(key)
    if prompt is None:
        return True  # промпт не задан — запуск задачи сам сообщит об этом ошибкой
    # Рендер — как в _submit (и в core/pipeline.py: _prepare_prompt), с датой запуска.
    llm_config = job.get("llm") or {}
    user_prompt = prompts_store.render_user_prompt(
        prompt["user"],
        max_theme=int(llm_config.get("max_theme", 10)),
        max_category=int(llm_config.get("max_category", 14)),
        now=run_at,
    )
    started = time.monotonic()
    try:
        text = provider.generate(prompt["system"], user_prompt,
                                 temperature=float(llm_config.get("temperature", 0.7))).strip()
    except Exception as exc:
        summary["failed"] += 1
        summary["reason"] = f"{key}: {exc}"[:300]
        return False
    created = clock()
    draft = {
        "id": f"{re.sub(r'[^A-Za-z0-9_-]', '_', key)[:40]}-{run_at:%Y%m%dT%H%M}-"
              f"{uuid.uuid4().hex[:6]}",
        "job": key,
        "run_at": _iso(run_at),
        "status": "ready",
        "provider": name,
        "batch_id": f"pregen-{created:%Y%m%dT%H%M}",
        "prompt_id": prompt["id"],
        "lead_minutes": DEFAULT_LEAD_MINUTES,
        "system": prompt["system"],
        "user": user_prompt,
        "text": text,
        "model": config.get("model"),
        "seconds": round(time.monotonic() - started, 1),
        "created_at": _iso(created),
        "ready_at": _iso(created),
    }
    with _state() as data:
        data["drafts"][draft["id"]] = draft
    summary["ok"] += 1
    logger.info("Вечерняя заготовка %s готова: %d символов за %.0f с",
                _label(draft), len(text), draft["seconds"])
    return True


def _read_trigger(path: str):
    """Время из файла-триггера (одна строка ISO) или None."""
    try:
        with open(path, encoding="utf-8") as file:
            moment = _parse(file.read().strip())
    except (OSError, ValueError):
        return None
    return moment if moment.tzinfo else moment.astimezone()


def _write_done(path: str, summary: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False)
    os.replace(tmp_path, path)


def pregen_check(now: datetime.datetime = None, background: bool = True) -> dict:
    """Раз в минуту (планировщик панели): новый триггер — запустить вечернюю заготовку.

    Триггер — файл pregen_trigger_file с временем ISO; срабатывает, если это время
    новее последнего обработанного и не старше PREGEN_TRIGGER_MAX_AGE_HOURS. Итог
    пишется в pregen_done_file. Заготовка идёт десятки минут, поэтому по умолчанию —
    в отдельном потоке (задание планировщика сразу освобождается). Исключений не
    бросает. Возвращает {"trigger": ...} (в потоке) или итог (background=False), иначе {}.
    """
    now = now or _now()
    try:
        configs = [config for _, config in pregen_providers()
                   if config.get("pregen_trigger_file")]
        if not configs:
            return {}
        config = configs[0]
        moment = _read_trigger(config["pregen_trigger_file"])
        if moment is None or now - moment > datetime.timedelta(hours=PREGEN_TRIGGER_MAX_AGE_HOURS):
            return {}
        with _state() as data:
            seen = data.setdefault("pregen", {}).get("last_trigger")
            if seen and _parse(seen) >= moment:
                return {}
            data["pregen"]["last_trigger"] = _iso(moment)
        logger.info("Вечерняя заготовка: триггер %s — начинаю", _iso(moment))
        if background:
            threading.Thread(target=_pregen_and_report, args=(config, moment, now),
                             name="pregen", daemon=True).start()
            return {"trigger": _iso(moment)}
        return _pregen_and_report(config, moment, now)
    except Exception as exc:
        logger.warning("Вечерняя заготовка: сбой проверки триггера — %s", exc)
        return {}


def _pregen_and_report(config: dict, moment: datetime.datetime, now: datetime.datetime) -> dict:
    """Заготовка и отчёт о ней: в состоянии и в pregen_done_file (его ждёт другая сторона)."""
    summary = pregenerate(now)
    summary["trigger"] = _iso(moment)
    try:
        with _state() as data:
            data.setdefault("pregen", {})["last_summary"] = summary
    except Exception as exc:
        logger.warning("Вечерняя заготовка: итог не записан в состояние — %s", exc)
    if config.get("pregen_done_file"):
        try:
            _write_done(config["pregen_done_file"], summary)
        except OSError as exc:
            logger.warning("Вечерняя заготовка: %s не записан — %s", config["pregen_done_file"], exc)
    logger.info("Вечерняя заготовка завершена: готово %d, ошибок %d%s", summary["ok"],
                summary["failed"], f" ({summary['reason']})" if summary["reason"] else "")
    return summary


# ------------------------------------------------------------------------ тик

def tick(now: datetime.datetime = None) -> dict:
    """Один проход: опрос пакетов → списание негодного → отправка нового пакета.

    Вызывается планировщиком панели в отдельном потоке и из CLI. Исключений не
    бросает; шаги независимы — сбой опроса не мешает отправке и наоборот.
    """
    now = now or _now()
    result = {"busy": False, "polled": [], "submitted": []}
    try:
        with _exclusive(".tick.lock", _tick_lock, blocking=False):
            for name, step in (("опрос пакетов", lambda: result["polled"].extend(poll(now))),
                               ("чистка", lambda: _housekeeping(now)),
                               ("отправка пакета", lambda: result["submitted"].extend(submit_due(now)))):
                try:
                    step()
                except Exception as exc:
                    logger.warning("Пакетная заготовка промптов: сбой шага «%s» — %s", name, exc)
    except _Busy:
        result["busy"] = True
        logger.info("Пакетная заготовка промптов: предыдущий тик ещё выполняется — пропуск")
    except Exception as exc:
        logger.warning("Пакетная заготовка промптов: сбой тика — %s", exc)
    return result


# ------------------------------------------------------------------------ CLI

def _print_status():
    with _state() as data:
        batches, drafts = dict(data["batches"]), list(data["drafts"].values())
    if not batches and not drafts:
        print("Пакетов и заготовок нет.")
        return
    print("Пакеты:")
    for batch_id, batch in sorted(batches.items(), key=lambda item: item[1]["submitted_at"]):
        print(f"  {batch_id} · LLM «{batch['provider']}» · {batch['status']} · "
              f"отправлен {batch['submitted_at']} · завершён {batch['ended_at'] or '—'}")
    print("Заготовки:")
    for draft in sorted(drafts, key=lambda d: (d["run_at"], d["job"])):
        start, end = _window(draft)
        usage = draft.get("usage") or {}
        print(f"  {draft['job']} · запуск {draft['run_at']} · {draft['status']} · "
              f"пакет {draft['batch_id']} · промпт #{draft['prompt_id']} · "
              f"годна {start:%d.%m %H:%M}–{end:%d.%m %H:%M}")
        if draft.get("text"):
            print(f"      {len(draft['text'])} символов, {draft.get('model')}, токены: вход "
                  f"{usage.get('input_tokens')}, выход {usage.get('output_tokens')}")
            print(f"      «{' '.join(draft['text'][:200].split())}…»")
        if draft.get("error"):
            print(f"      причина: {draft['error']}")


def _main(argv: list) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    command = argv[0] if argv else ""
    if command == "status" and len(argv) == 1:
        _print_status()
    elif command == "tick" and len(argv) == 1:
        result = tick()
        if result["busy"]:
            print("Тик уже выполняется (панель или другой CLI) — повторите позже.")
            return 1
        for line in result["polled"]:
            print("Опрос:", line)
        print("Отправлено пакетов:", ", ".join(result["submitted"]) or "нет")
    elif command == "pregen" and len(argv) == 1:
        # Ручной запуск: шлёт запросы в Qwen2API — только по согласованию (квота общая).
        summary = pregenerate()
        print(f"Вечерняя заготовка: готово {summary['ok']}, ошибок {summary['failed']}"
              + (f", причина: {summary['reason']}" if summary["reason"] else ""))
    elif (command == "submit" and len(argv) > 1) or (command == "poll" and len(argv) == 1):
        try:
            # под тем же замком, что и тик панели: иначе два процесса могли бы
            # отправить пакет на один и тот же запуск
            with _exclusive(".tick.lock", _tick_lock, blocking=False):
                if command == "submit":
                    sent = submit_forced(argv[1:])
                    print("Отправлено пакетов:", ", ".join(sent) or "нет")
                else:
                    for line in poll() or ["Отправленных пакетов в обработке нет."]:
                        print("Опрос:", line)
        except _Busy:
            print("Тик уже выполняется (панель или другой CLI) — повторите позже.")
            return 1
    else:
        print("Использование: python -m core.prompt_batches status | tick | "
              "submit <ключи задач...> | poll | pregen")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
