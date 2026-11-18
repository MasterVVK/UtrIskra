"""Самопроверка пакетной заготовки промптов (core/prompt_batches.py) — без сети.

Запуск из корня проекта (pytest в .venv нет, поэтому на stdlib-unittest;
pytest, если появится, подхватит эти же тесты):

    .venv/bin/python -m unittest tests.test_prompt_batches -v

Клиент Anthropic подменён заглушкой, но ответы собраны настоящими моделями SDK
(MessageBatch, MessageBatchIndividualResponse) — так проверяется и разбор полей.
Файл состояния и база промптов — во временном каталоге; живые storage/ и
providers.json/jobs.json/schedule.json тесты не читают и не трогают.
"""
import asyncio
import datetime
import inspect
import json
import logging
import os
import random
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic  # noqa: E402
import httpx2  # noqa: E402
from anthropic.types import Message  # noqa: E402
from anthropic.types.messages import MessageBatch, MessageBatchIndividualResponse  # noqa: E402

from core import jobs as jobs_store  # noqa: E402
from core import pipeline  # noqa: E402
from core import prompt_batches as pb  # noqa: E402
from core import prompts as prompts_store  # noqa: E402
from core import providers_store  # noqa: E402
from providers.llm.anthropic_claude import AnthropicProvider  # noqa: E402
from webapp import schedule_store  # noqa: E402
from webapp import scheduler_service  # noqa: E402


def at(hour, minute, day=18):
    """Момент по локальному времени сервера — в нём же считает планировщик."""
    return datetime.datetime(2026, 11, day, hour, minute).astimezone()


NOW = at(2, 30)  # до hidream (04:30) ровно lead = 120 минут


def job(pipeline_name="image", provider=None, archived=False, max_theme=10):
    return {"title": "t", "pipeline": pipeline_name, "file_prefix": "p", "archived": archived,
            "llm": {"provider": provider, "temperature": 0.7,
                    "max_theme": max_theme, "max_category": 14}}


JOBS = {
    "hidream": job(max_theme=50),
    "zimage": job(),
    "qwen": job(),
    "dalle": job(),
    "mjvideo": job("midjourney_video"),       # тоже берёт промпт через _prepare_prompt
    "late": job(),                            # 09:00 — за горизонтом 360 минут
    "off": job(),                             # выключена в расписании
    "archived": job(archived=True),
    "bestof": {"title": "b", "pipeline": "best_image_video", "file_prefix": "b"},
    "own_llm": job(provider="gemini"),        # свой провайдер — не batch-инстанс
}
SCHEDULE = {
    "hidream": (True, 4, 30), "zimage": (True, 5, 0), "qwen": (True, 6, 0),
    "dalle": (True, 7, 30), "mjvideo": (True, 8, 0), "late": (True, 9, 0),
    "off": (False, 5, 0), "archived": (True, 5, 0),
    "bestof": (True, 5, 0), "own_llm": (True, 5, 0),
}
IN_WINDOW = ["dalle", "hidream", "mjvideo", "qwen", "zimage"]


def providers(batch=True, chain=("opus", "qwen-fallback", "gemini"), **extra):
    opus = {"type": "anthropic", "model": "claude-opus-5-5", "effort": "high", **extra}
    if batch:
        opus["batch"] = True
    return {"llm": {"opus": opus,
                    "qwen-fallback": {"type": "openai", "base_url": "http://x/v1", "model": "q"},
                    "gemini": {"type": "gemini", "model": "g"}},
            "llm_chain": list(chain), "image": {}}


def message(text="Готовый текст", stop_reason="end_turn", **extra):
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 3400}, **extra}


def succeeded(**kwargs):
    return {"type": "succeeded", "message": message(**kwargs)}


REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages/batches")


class FakeBatches:
    """Заглушка client.messages.batches: помнит отправленное, отдаёт заданное."""

    def __init__(self):
        self.created = []           # список пакетов; пакет — список Request
        self.client_options = []    # с какими параметрами создавался клиент
        self.outcomes = {}          # batch_id -> callable(custom_ids) -> {custom_id: result}
        self.ended = set()
        self.create_error = None
        self.retrieve_error = None
        self.retrieve_calls = 0

    def create(self, *, requests):
        if self.create_error is not None:
            raise self.create_error
        self.created.append(list(requests))
        return SimpleNamespace(id=f"msgbatch_test{len(self.created)}",
                               processing_status="in_progress")

    def retrieve(self, batch_id):
        self.retrieve_calls += 1
        if self.retrieve_error is not None:
            raise self.retrieve_error
        ended = batch_id in self.ended
        return MessageBatch.model_validate({
            "id": batch_id, "type": "message_batch",
            "processing_status": "ended" if ended else "in_progress",
            "created_at": "2026-11-18T02:30:00Z", "expires_at": "2026-11-19T02:30:00Z",
            "ended_at": "2026-11-18T03:10:00Z" if ended else None,
            "request_counts": {"processing": 0 if ended else 1, "succeeded": 0, "errored": 0,
                               "canceled": 0, "expired": 0},
            "results_url": None})

    def results(self, batch_id):
        index = int(batch_id.removeprefix("msgbatch_test")) - 1
        custom_ids = [request["custom_id"] for request in self.created[index]]
        outcomes = self.outcomes[batch_id](custom_ids)
        lines = [MessageBatchIndividualResponse.model_validate(
            {"custom_id": custom_id, "result": result}) for custom_id, result in outcomes.items()]
        random.Random(7).shuffle(lines)  # API порядок не гарантирует
        return iter(lines)

    def finish(self, batch_id, by_job=None, default=None):
        """Пакет завершён; by_job — результат по ключу задачи (custom_id начинается с него)."""
        self.ended.add(batch_id)
        self.outcomes[batch_id] = lambda custom_ids: {
            custom_id: (by_job or {}).get(custom_id.rsplit("-", 2)[0], default or succeeded())
            for custom_id in custom_ids}


class BatchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = os.path.join(self.tmp.name, "webapp", "prompt_batches.json")
        self.batches = FakeBatches()
        self.providers = providers()
        test = self

        class FakeClient:
            messages = SimpleNamespace(batches=self.batches)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_client(provider, **overrides):
            test.batches.client_options.append(overrides)
            return FakeClient()

        for target, attribute, value in (
            (pb, "STATE_PATH", self.state_path),
            (prompts_store, "DB_PATH", os.path.join(self.tmp.name, "db", "prompts.db")),
            (jobs_store, "load_jobs", lambda: JOBS),
            (schedule_store, "load_schedule", lambda: {
                key: {"enabled": enabled, "hour": hour, "minute": minute}
                for key, (enabled, hour, minute) in SCHEDULE.items()}),
            (providers_store, "load_providers", lambda: self.providers),
            (AnthropicProvider, "_client", fake_client),
        ):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        prompts_store.initialize()
        with sqlite3.connect(prompts_store.DB_PATH) as conn:
            conn.executemany(
                "INSERT INTO job_prompts (job_key, system_prompt, user_prompt, updated_at) "
                "VALUES (?, ?, ?, '2026-11-01T00:00:00')",
                [(key, f"system {key}", f"user {key} date={{current_date}} "
                                        f"theme={{random_theme}} seed={{random_seed}}")
                 for key, data in JOBS.items() if "llm" in data])

    # -- помощники

    def state(self):
        with open(self.state_path, encoding="utf-8") as file:
            return json.load(file)

    def drafts(self, status=None):
        return {draft["job"]: draft for draft in self.state()["drafts"].values()
                if status is None or draft["status"] == status}

    def prompt_id(self, key):
        return prompts_store.get_prompt(key)["id"]

    def sent_jobs(self, index=-1):
        return sorted(request["custom_id"].rsplit("-", 2)[0]
                      for request in self.batches.created[index])

    def ready(self, by_job=None, when=None):
        """Отправить пакет на NOW и получить результаты."""
        pb.tick(NOW)
        self.batches.finish("msgbatch_test1", by_job)
        pb.tick(when or at(3, 15))


class WindowTests(BatchTestCase):
    def test_one_batch_for_all_runs_in_window(self):
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            result = pb.tick(NOW)
        self.assertEqual(result["submitted"], ["msgbatch_test1"])
        self.assertEqual(len(self.batches.created), 1)
        # в окне [сейчас+10 мин; сейчас+360 мин]: без late, off, archived,
        # bestof (пайплайн без промпта) и own_llm (первый провайдер — не batch)
        self.assertEqual(self.sent_jobs(), IN_WINDOW)
        self.assertTrue(any("Отправлен пакет msgbatch_test1" in line and "hidream на 18.11 04:30"
                            in line for line in logs.output))
        drafts = self.drafts("pending")
        self.assertEqual(sorted(drafts), IN_WINDOW)
        self.assertEqual(pb._parse(drafts["dalle"]["run_at"]), at(7, 30))
        self.assertEqual(drafts["zimage"]["batch_id"], "msgbatch_test1")
        self.assertEqual(drafts["zimage"]["prompt_id"], self.prompt_id("zimage"))

    def test_waits_until_nearest_run_is_within_lead(self):
        self.assertEqual(pb.tick(at(2, 29))["submitted"], [])   # до 04:30 ещё 121 минута
        self.assertEqual(self.batches.created, [])
        self.assertFalse(os.path.exists(self.state_path))       # впустую файл не пишется
        self.assertEqual(pb.tick(at(2, 30))["submitted"], ["msgbatch_test1"])

    def test_run_closer_than_10_minutes_is_left_to_the_chain(self):
        soon = {"soon9": (True, 2, 39), "soon10": (True, 2, 40)}
        with mock.patch.dict(JOBS, {key: job() for key in soon}), mock.patch.dict(SCHEDULE, soon):
            for key in soon:
                prompts_store.save_prompt(key, "s", "u")
            pb.tick(NOW)
        self.assertEqual(self.sent_jobs(), sorted(IN_WINDOW + ["soon10"]))

    def test_lead_and_horizon_come_from_instance_config(self):
        self.providers = providers(batch_lead_minutes=30, batch_horizon_minutes=100)
        self.assertEqual(pb.tick(NOW)["submitted"], [])          # 120 > lead 30
        pb.tick(at(4, 0))                                        # до hidream 30 минут
        self.assertEqual(self.sent_jobs(), ["hidream", "zimage"])  # горизонт до 05:40

    def test_request_params_match_sync_provider_and_batch_limits(self):
        self.providers = providers(max_tokens=20000, effort="xhigh")
        pb.tick(NOW)
        request = next(r for r in self.batches.created[0] if r["custom_id"].startswith("zimage-"))
        draft = self.drafts()["zimage"]
        params = request["params"]
        self.assertEqual(params["model"], "claude-opus-5-5")
        self.assertEqual(params["max_tokens"], 20000)
        self.assertEqual(params["output_config"], {"effort": "xhigh"})
        self.assertEqual(params["system"], "system zimage")
        self.assertEqual(params["messages"], [{"role": "user", "content": draft["user"]}])
        for forbidden in ("stream", "fallbacks", "betas", "temperature", "top_p", "speed"):
            self.assertNotIn(forbidden, params)
        self.assertRegex(request["custom_id"], r"^[A-Za-z0-9_-]{1,64}$")
        self.assertEqual(len({r["custom_id"] for r in self.batches.created[0]}), 5)
        # создание пакета не идемпотентно — авто-повторы SDK выключены
        self.assertEqual(self.batches.client_options[-1].get("max_retries"), 0)

    def test_prompt_is_rendered_like_pipeline_for_the_run_date(self):
        self.providers = providers(batch_lead_minutes=340, batch_horizon_minutes=340)
        random.seed(42)
        pb.tick(at(23, 0, day=17))            # отправка 17-го…
        self.assertEqual(self.sent_jobs(), ["hidream"])
        draft = self.drafts()["hidream"]
        self.assertEqual(pb._parse(draft["run_at"]), at(4, 30))   # …запуск 18-го
        # тот же ГСЧ и «сегодня = день запуска»: пайплайн обязан отрендерить то же самое

        class RunDay(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 18, 4, 30)

        self.providers = providers(batch=False)       # чтобы пайплайн не взял заготовку
        random.seed(42)
        with mock.patch.object(prompts_store.datetime, "datetime", RunDay), \
                mock.patch.object(pipeline, "_generate_text", return_value="x"):
            system, user, _ = pipeline._prepare_prompt("hidream", JOBS["hidream"])
        self.assertEqual((draft["system"], draft["user"]), (system, user))
        self.assertIn("theme=", user)
        self.assertIn("date=18 November 2026", draft["user"])
        self.assertNotIn("{", draft["user"])

    def test_flag_off_or_instance_not_first_means_no_batches(self):
        for self.providers in (providers(batch=False),
                               providers(chain=("gemini", "opus")),
                               providers(chain=())):
            self.assertEqual(pb.tick(NOW), {"busy": False, "polled": [], "submitted": []})
        self.assertEqual(self.batches.created, [])
        self.assertEqual(self.batches.client_options, [])       # в сеть не ходили вовсе

    def test_job_own_provider_can_be_the_batch_instance(self):
        self.providers = providers(batch=False)
        self.providers["llm"]["opus-batch"] = {"type": "anthropic", "batch": True}
        with mock.patch.dict(JOBS, {"zimage": job(provider="opus-batch")}):
            pb.tick(at(3, 0))
        self.assertEqual(self.sent_jobs(), ["zimage"])
        self.assertEqual(self.drafts()["zimage"]["provider"], "opus-batch")


class NoDoubleSubmitTests(BatchTestCase):
    def test_next_ticks_do_not_resubmit(self):
        pb.tick(NOW)
        for moment in (at(2, 35), at(2, 40), at(3, 0)):
            self.assertEqual(pb.tick(moment)["submitted"], [])
        self.batches.finish("msgbatch_test1")
        for moment in (at(3, 15), at(3, 20), at(4, 25)):
            self.assertEqual(pb.tick(moment)["submitted"], [])
        self.assertEqual(len(self.batches.created), 1)

    def test_state_survives_restart(self):
        pb.tick(NOW)
        saved = self.state()
        # «перезапуск»: в памяти модуля ничего нет, всё читается из файла
        self.assertEqual(pb.tick(at(2, 35))["submitted"], [])
        self.assertEqual(self.state(), saved)

    def test_only_runs_without_draft_go_into_the_next_batch(self):
        pb.tick(NOW)
        # включили задачу на 05:00, а 09:00 тем временем вошло в горизонт
        with mock.patch.dict(SCHEDULE, {"off": (True, 5, 0)}):
            pb.tick(at(3, 0))
        self.assertEqual(self.sent_jobs(), ["late", "off"])
        self.assertEqual(len(self.batches.created), 2)

    def test_failed_result_is_not_requested_again_for_same_run(self):
        self.ready({"zimage": {"type": "expired"}})
        self.assertEqual(self.drafts("failed").keys(), {"zimage"})
        self.assertEqual(pb.tick(at(3, 20))["submitted"], [])
        self.assertEqual(len(self.batches.created), 1)

    def test_concurrent_tick_is_skipped_not_doubled(self):
        with pb._exclusive(".tick.lock", pb._tick_lock):
            done = []
            thread = threading.Thread(target=lambda: done.append(pb.tick(NOW)))
            thread.start()
            thread.join(10)
        self.assertEqual(done, [{"busy": True, "polled": [], "submitted": []}])
        self.assertEqual(self.batches.created, [])

    def test_forced_submit_ignores_flag_but_not_existing_drafts(self):
        self.providers = providers(batch=False)
        self.assertEqual(pb.submit_forced(["zimage", "off", "bestof", "own_llm", "nope"], NOW),
                         ["msgbatch_test1"])
        self.assertEqual(self.sent_jobs(), ["off", "zimage"])
        drafts = self.drafts()
        self.assertEqual(pb._parse(drafts["zimage"]["run_at"]), at(5, 0))   # ближайший запуск
        self.assertEqual(pb._parse(drafts["off"]["run_at"]), NOW)           # расписание выключено
        self.assertEqual(pb.submit_forced(["zimage", "qwen"], at(2, 40)), ["msgbatch_test2"])
        self.assertEqual(self.sent_jobs(), ["qwen"])
        # включили флаг: тик не дублирует то, что уже заказано вручную
        self.providers = providers()
        pb.tick(at(2, 45))
        self.assertEqual(self.sent_jobs(), ["dalle", "hidream", "mjvideo"])


class ResultTests(BatchTestCase):
    def test_results_are_matched_by_custom_id(self):
        pb.tick(NOW)
        self.batches.finish("msgbatch_test1", {
            "hidream": succeeded(text="  Текст для hidream  "),
            "zimage": {"type": "errored", "error": {"type": "error", "request_id": "req_1", "error": {
                "type": "invalid_request_error", "message": "max_tokens: too large"}}},
            "qwen": {"type": "expired"},
            "dalle": succeeded(text=None, stop_reason="refusal", stop_details={
                "type": "refusal", "category": "general_harms", "explanation": "…"}),
            "mjvideo": succeeded(text="оборванный на полусло", stop_reason="max_tokens"),
        })
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            result = pb.tick(at(3, 15))
        self.assertIn("готово 1, отказов 4, шёл 40 мин", result["polled"][0])
        self.assertTrue(any("Пакет msgbatch_test1 завершён: готово 1, отказов 4, шёл 40 мин, "
                            "токены: вход 1200, выход 3400" in line for line in logs.output))
        drafts = self.drafts()
        self.assertEqual(drafts["hidream"]["status"], "ready")
        self.assertEqual(drafts["hidream"]["text"], "Текст для hidream")
        self.assertEqual(drafts["hidream"]["usage"], {"input_tokens": 1200, "output_tokens": 3400})
        self.assertEqual(drafts["hidream"]["model"], "claude-opus-5-5")
        reasons = {key: drafts[key]["error"] for key in ("zimage", "qwen", "dalle", "mjvideo")}
        self.assertIn("invalid_request_error", reasons["zimage"])
        self.assertIn("max_tokens: too large", reasons["zimage"])
        self.assertIn("просрочен", reasons["qwen"])
        self.assertIn("отклонила запрос (категория general_harms)", reasons["dalle"])
        self.assertIn("оборван по max_tokens=32000", reasons["mjvideo"])
        for key in reasons:
            self.assertEqual(drafts[key]["status"], "failed")
            self.assertNotIn("text", drafts[key])
            self.assertTrue(any(f"«{key}»" in line and "не получена" in line
                                for line in logs.output if "WARNING" in line))
        self.assertEqual(self.state()["batches"]["msgbatch_test1"]["status"], "ended")
        # отказ — не текст: пайплайн заготовку не получит
        self.assertIsNone(pb.take_draft("dalle", JOBS["dalle"], prompts_store.get_prompt("dalle"), at(7, 30)))

    def test_canceled_empty_and_missing_results_are_failures(self):
        pb.tick(NOW)
        self.batches.ended.add("msgbatch_test1")
        self.batches.outcomes["msgbatch_test1"] = lambda custom_ids: {
            custom_ids[0]: {"type": "canceled"},
            custom_ids[1]: succeeded(text="   "),
            "чужой-id": succeeded(),
        }
        pb.tick(at(3, 15))
        self.assertEqual(len(self.drafts("failed")), 5)
        self.assertEqual(self.drafts("ready"), {})
        errors = " | ".join(draft["error"] for draft in self.drafts().values())
        for expected in ("отменён", "пустой ответ", "нет ответа на этот запрос"):
            self.assertIn(expected, errors)

    def test_batch_in_progress_is_polled_again(self):
        pb.tick(NOW)
        self.assertIn("in_progress", pb.tick(at(2, 35))["polled"][0])
        self.assertEqual(len(self.drafts("pending")), 5)
        self.batches.finish("msgbatch_test1")
        pb.tick(at(2, 40))
        self.assertEqual(len(self.drafts("ready")), 5)
        calls = self.batches.retrieve_calls
        pb.tick(at(2, 45))                       # завершённый пакет больше не опрашивается
        self.assertEqual(self.batches.retrieve_calls, calls)

    def test_batch_gone_on_api_side(self):
        pb.tick(NOW)
        self.batches.retrieve_error = anthropic.NotFoundError(
            "not found", response=httpx2.Response(404, request=REQUEST), body=None)
        pb.tick(at(2, 35))
        self.assertEqual(self.state()["batches"]["msgbatch_test1"]["status"], "lost")
        self.assertEqual(len(self.drafts("failed")), 5)


class DraftValidityTests(BatchTestCase):
    def take(self, key, when):
        return pb.take_draft(key, JOBS[key], prompts_store.get_prompt(key), when)

    def test_ready_draft_is_taken_once(self):
        self.ready()
        draft = self.take("zimage", at(5, 0))
        self.assertEqual(draft["text"], "Готовый текст")
        self.assertEqual(draft["batch_id"], "msgbatch_test1")
        self.assertEqual(self.drafts()["zimage"]["status"], "used")
        self.assertIsNone(self.take("zimage", at(5, 1)))            # использована
        self.assertEqual(self.drafts()["qwen"]["status"], "ready")  # чужие не тронуты

    def test_usable_only_around_planned_time(self):
        self.ready()
        # zimage на 05:00, lead 120 + запас 30: годна с 02:30 до 17:00
        self.assertIsNone(self.take("zimage", at(2, 29)))
        self.assertEqual(self.drafts()["zimage"]["status"], "ready")   # рано — но цела
        self.assertIsNotNone(self.take("zimage", at(2, 30)))           # ручной запуск заранее
        self.assertIsNotNone(self.take("qwen", at(18, 0)))             # 06:00 + 12 ч — ещё годна
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            self.assertIsNone(self.take("hidream", at(16, 31)))        # 04:30 + 12 ч прошло
        self.assertEqual(self.drafts()["hidream"]["status"], "expired")
        self.assertTrue(any("«hidream» на 18.11 04:30 просрочена" in line for line in logs.output))

    def test_changed_prompt_version_discards_draft(self):
        self.ready()
        prompts_store.save_prompt("zimage", "system zimage", "новый user {random_theme}")
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            self.assertIsNone(self.take("zimage", at(5, 0)))
        self.assertEqual(self.drafts()["zimage"]["status"], "stale")
        self.assertTrue(any("отброшена: промпт задачи с тех пор изменился" in line
                            for line in logs.output))
        self.assertIsNotNone(self.take("qwen", at(6, 0)))

    def test_changed_prompt_is_requested_again_while_there_is_time(self):
        self.ready()
        prompts_store.save_prompt("dalle", "system dalle", "новый user")
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            self.assertEqual(pb.tick(at(3, 20))["submitted"], [])   # до 07:30 больше lead
        self.assertTrue(any("«dalle» на 18.11 07:30 отброшена" in line for line in logs.output))
        pb.tick(at(5, 30))                                          # до 07:30 — 120 минут
        self.assertEqual(self.sent_jobs(), ["dalle", "late"])       # late вошла в горизонт
        self.batches.finish("msgbatch_test2", default=succeeded(text="по новому промпту"))
        pb.tick(at(6, 10))
        self.assertEqual(self.take("dalle", at(7, 30))["text"], "по новому промпту")
        statuses = sorted(d["status"] for d in self.state()["drafts"].values() if d["job"] == "dalle")
        self.assertEqual(statuses, ["stale", "used"])

    def test_pending_draft_is_not_given_out(self):
        pb.tick(NOW)
        with self.assertLogs("core.prompt_batches", "INFO") as logs:
            self.assertIsNone(self.take("hidream", at(4, 30)))
        self.assertTrue(any("ещё не готова (пакет msgbatch_test1" in line for line in logs.output))
        self.assertEqual(self.drafts()["hidream"]["status"], "pending")

    def test_flag_switched_off_stops_using_drafts(self):
        self.ready()
        self.providers = providers(batch=False)
        self.assertIsNone(self.take("zimage", at(5, 0)))
        self.providers = providers(chain=("gemini", "opus"))
        self.assertIsNone(self.take("zimage", at(5, 0)))
        self.assertEqual(self.drafts()["zimage"]["status"], "ready")

    def test_two_threads_cannot_take_the_same_draft(self):
        self.ready()
        taken = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            taken.append(self.take("zimage", at(5, 0)))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len([draft for draft in taken if draft is not None]), 1)

    def test_old_records_are_cleaned_up(self):
        self.ready()
        pb.tick(at(2, 29, day=21))               # 3 суток без минуты: записи ещё есть
        self.assertEqual(len(self.state()["drafts"]), 5)
        self.assertEqual({d["status"] for d in self.state()["drafts"].values()}, {"expired"})
        pb.tick(at(2, 31, day=21))               # старое удалено, отправлен пакет на 21-е
        self.assertEqual({d["batch_id"] for d in self.state()["drafts"].values()},
                         {"msgbatch_test2"})
        self.assertEqual(list(self.state()["batches"]), ["msgbatch_test2"])


class FailureTests(BatchTestCase):
    def write_state(self, text):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as file:
            file.write(text)

    def test_broken_state_file_is_set_aside(self):
        naive_time = json.dumps({"drafts": {"x": {
            "job": "zimage", "status": "ready", "provider": "opus", "prompt_id": 1,
            "batch_id": "b", "run_at": "2026-11-18T05:00:00", "created_at": "2026-11-18T02:30:00"}}})
        for broken in ('{"drafts": {"x": ', "[1, 2]", '{"drafts": {"x": {"job": "zimage"}}}',
                       '{"drafts": [], "batches": {}}', "\x00\x01", naive_time):
            self.write_state(broken)
            with self.assertLogs("core.prompt_batches", "WARNING") as logs:
                self.assertIsNone(pb.take_draft("zimage", JOBS["zimage"], {"id": 1}, at(5, 0)))
            self.assertIn("файл состояния повреждён", logs.output[0])
            self.assertFalse(os.path.exists(self.state_path))
        aside = [name for name in os.listdir(os.path.dirname(self.state_path)) if ".broken-" in name]
        self.assertTrue(aside)
        # после этого механизм работает с чистого листа
        self.assertEqual(pb.tick(NOW)["submitted"], ["msgbatch_test1"])

    def test_broken_state_does_not_break_the_tick(self):
        self.write_state("не json")
        with self.assertLogs("core.prompt_batches", "WARNING"):
            result = pb.tick(NOW)
        self.assertEqual(result["submitted"], ["msgbatch_test1"])

    def test_read_error_is_not_treated_as_broken_file(self):
        # прочитать не удалось (здесь — на месте файла каталог): это не «битый
        # файл», переносить его нельзя; заготовки нет — обычная цепочка
        os.makedirs(self.state_path)
        with self.assertLogs("core.prompt_batches", "WARNING") as logs:
            self.assertIsNone(pb.take_draft("zimage", JOBS["zimage"], {"id": 1}, at(5, 0)))
            self.assertEqual(pb.tick(NOW)["submitted"], [])
        self.assertIn("обычная цепочка LLM", logs.output[0])
        self.assertTrue(os.path.isdir(self.state_path))
        self.assertEqual([name for name in os.listdir(os.path.dirname(self.state_path))
                          if ".broken-" in name], [])

    def test_unreadable_state_dir_falls_back_to_chain(self):
        with mock.patch.object(pb, "STATE_PATH", "/proc/нет/такого/prompt_batches.json"):
            with self.assertLogs("core.prompt_batches", "WARNING") as logs:
                self.assertIsNone(pb.take_draft("zimage", JOBS["zimage"], {"id": 1}, at(5, 0)))
                self.assertEqual(pb.tick(NOW), {"busy": False, "polled": [], "submitted": []})
        self.assertIn("обычная цепочка LLM", logs.output[0])

    def test_submit_errors_do_not_raise_and_are_retried_later(self):
        for error in (anthropic.APIConnectionError(request=REQUEST),
                      anthropic.BadRequestError("bad request", body=None,
                                                response=httpx2.Response(400, request=REQUEST)),
                      anthropic.InternalServerError("overloaded", body=None,
                                                    response=httpx2.Response(529, request=REQUEST)),
                      RuntimeError("LLM «opus»: не задан ключ")):
            with self.subTest(error=type(error).__name__):
                if os.path.exists(self.state_path):
                    os.remove(self.state_path)
                self.batches.created.clear()
                self.batches.create_error = error
                with self.assertLogs("core.prompt_batches", "WARNING") as logs:
                    self.assertEqual(pb.tick(NOW)["submitted"], [])
                self.assertIn("не отправлен", logs.output[0])
                self.assertEqual(self.drafts(), {})          # неотправленное не записано
                self.batches.create_error = None
                self.assertEqual(pb.tick(at(2, 35))["submitted"], [])    # пауза 15 минут
                self.assertEqual(pb.tick(at(2, 45))["submitted"], ["msgbatch_test1"])
                self.assertEqual(self.sent_jobs(), IN_WINDOW)

    def test_poll_errors_keep_batch_for_next_tick(self):
        pb.tick(NOW)
        self.batches.finish("msgbatch_test1")
        self.batches.retrieve_error = anthropic.APIConnectionError(request=REQUEST)
        with self.assertLogs("core.prompt_batches", "WARNING") as logs:
            result = pb.tick(at(2, 35))
        self.assertIn("опрос не удался", logs.output[0])
        self.assertEqual(result["submitted"], [])
        self.assertEqual(len(self.drafts("pending")), 5)
        self.batches.retrieve_error = None
        pb.tick(at(2, 40))
        self.assertEqual(len(self.drafts("ready")), 5)

    def test_poll_failure_does_not_block_submit(self):
        with mock.patch.object(pb, "poll", side_effect=RuntimeError("сломалось")):
            with self.assertLogs("core.prompt_batches", "WARNING") as logs:
                self.assertEqual(pb.tick(NOW)["submitted"], ["msgbatch_test1"])
        self.assertIn("сбой шага «опрос пакетов»", logs.output[0])


class PipelineTests(BatchTestCase):
    def prepare(self, key, when):
        with mock.patch.object(pb, "_now", lambda: when), \
                mock.patch.object(pipeline, "_generate_text", return_value="синхронный") as chain:
            return pipeline._prepare_prompt(key, JOBS[key]), chain

    def test_prepare_prompt_takes_draft_with_its_rendered_prompts(self):
        self.ready({"zimage": succeeded(text="заготовленный текст")})
        stored = self.drafts()["zimage"]
        with self.assertLogs("core.pipeline", "INFO") as logs:
            (system, user, generated), chain = self.prepare("zimage", at(5, 0))
        self.assertEqual((system, user, generated),
                         (stored["system"], stored["user"], "заготовленный текст"))
        chain.assert_not_called()
        self.assertTrue(any("промпт взят из пакетной заготовки (пакет msgbatch_test1" in line
                            for line in logs.output))
        # повторный (ручной) запуск: заготовка использована — обычная цепочка, свежий рендер
        (system, user, generated), chain = self.prepare("zimage", at(5, 10))
        self.assertEqual(generated, "синхронный")
        chain.assert_called_once_with(JOBS["zimage"], system, user)
        self.assertNotEqual(user, stored["user"])
        self.assertNotIn("{", user)

    def test_prepare_prompt_without_draft_uses_chain(self):
        for self.providers in (providers(), providers(batch=False)):
            (system, user, generated), chain = self.prepare("qwen", at(6, 0))
            self.assertEqual((system, generated), ("system qwen", "синхронный"))
            chain.assert_called_once_with(JOBS["qwen"], system, user)

    def test_prepare_prompt_survives_broken_batch_mechanism(self):
        self.ready()
        with mock.patch.object(pb, "_take", side_effect=OSError("диск отвалился")):
            with self.assertLogs("core.prompt_batches", "WARNING") as logs:
                (_, _, generated), chain = self.prepare("zimage", at(5, 0))
        self.assertEqual(generated, "синхронный")
        chain.assert_called_once()
        self.assertIn("обычная цепочка LLM", logs.output[0])

    def test_prompt_pipelines_list_matches_pipeline_code(self):
        uses_prompt = tuple(name for name, runner in pipeline.PIPELINES.items()
                            if "_prepare_prompt(" in inspect.getsource(runner))
        self.assertEqual(uses_prompt, pb.PROMPT_PIPELINES)

    def test_batch_instance_is_the_first_llm_the_pipeline_would_call(self):
        """batch_provider и _generate_text выбирают первый LLM одной и той же развилкой."""
        self.providers["llm"]["claude2"] = {"type": "anthropic", "batch": True}
        tried = []

        def fake_build(name, config):
            tried.append(name)
            return SimpleNamespace(generate=lambda *args, **kwargs: "текст")

        for own in (None, "claude2", "gemini"):
            for chain in (("opus", "gemini"), ("gemini", "opus"), ("claude2",)):
                self.providers["llm_chain"] = list(chain)
                tried.clear()
                with mock.patch.object(pipeline, "build_llm_provider", fake_build):
                    pipeline._generate_text(job(provider=own), "s", "u")
                first = self.providers["llm"][tried[0]]
                expected = tried[0] if first["type"] == "anthropic" and first.get("batch") else None
                found = pb.batch_provider(job(provider=own))
                self.assertEqual(found[0] if found else None, expected, (own, chain))

    def test_not_restarted_service_keeps_working_without_drafts(self):
        """Процесс, не перезапущенный после обновления, импортирует новый pipeline
        лениво — поверх СТАРОГО core.prompts в памяти (get_prompt без id,
        render_user_prompt без now). Запуски должны пройти обычной цепочкой."""
        self.ready()
        row = prompts_store.get_prompt("zimage")
        old_row = {name: value for name, value in row.items() if name != "id"}

        def old_render(user_prompt, max_theme=10, max_category=14):
            return f"отрендерено по-старому: {max_theme}/{max_category}"

        for flag in (False, True):
            self.providers = providers(batch=flag)
            with mock.patch.object(prompts_store, "get_prompt", lambda key: old_row), \
                    mock.patch.object(prompts_store, "render_user_prompt", old_render), \
                    mock.patch.object(pb, "_now", lambda: at(5, 0)), \
                    mock.patch.object(pipeline, "_generate_text", return_value="синхронный"):
                system, user, generated = pipeline._prepare_prompt("zimage", JOBS["zimage"])
            self.assertEqual((system, user, generated),
                             ("system zimage", "отрендерено по-старому: 10/14", "синхронный"))
            self.assertEqual(self.drafts()["zimage"]["status"], "ready")   # заготовка цела


class SyncProviderTests(unittest.TestCase):
    """Общая сборка параметров не должна была изменить синхронный вызов."""

    def generate(self, final_message, **config):
        calls = []

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return Message.model_validate(final_message)

        class Client:
            beta = SimpleNamespace(messages=SimpleNamespace(
                stream=lambda **params: calls.append(params) or Stream()))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        provider = AnthropicProvider("opus", {"type": "anthropic", **config})
        with mock.patch.object(AnthropicProvider, "_client", lambda self, **kw: Client()):
            return provider.generate("sys", "usr", temperature=1.0), calls[0]

    def test_sync_request_is_unchanged(self):
        text, params = self.generate(message(text=" ответ "))
        self.assertEqual(text, "ответ")
        self.assertEqual(params, {
            "model": "claude-opus-5-5", "max_tokens": 32000,
            "messages": [{"role": "user", "content": "usr"}],
            "output_config": {"effort": "high"}, "system": "sys",
            "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"})

    def test_sync_refusal_and_truncation_still_raise(self):
        for final, expected in ((message(text=None, stop_reason="refusal"), "отклонила запрос"),
                                (message(stop_reason="max_tokens"), "оборван по max_tokens"),
                                (message(text=None), "пустой ответ")):
            with self.assertRaisesRegex(RuntimeError, expected):
                self.generate(final)


class SchedulerTests(BatchTestCase):
    def test_tick_is_registered_next_to_cron_jobs_and_runs_in_a_thread(self):
        threads = []

        async def scenario():
            service = scheduler_service.SchedulerService(task_manager=None)
            with self.assertLogs("webapp.scheduler_service", "INFO") as logs:
                service.start()
            try:
                jobs = {scheduled.id: scheduled for scheduled in service.scheduler.get_jobs()}
                with mock.patch.object(pb, "tick",
                                       lambda: threads.append(threading.get_ident())):
                    await service._batch_tick()
                with mock.patch.object(pb, "tick", side_effect=RuntimeError("упал")):
                    await service._batch_tick()          # не должен бросить
                return jobs, logs.output, service.next_run("hidream")
            finally:
                service.shutdown()

        with mock.patch.object(scheduler_service, "get_generators", lambda: [
                SimpleNamespace(key=key, archived=bool(JOBS[key].get("archived"))) for key in JOBS]):
            jobs, output, next_hidream = asyncio.run(scenario())
        enabled = {key for key, (on, _, _) in SCHEDULE.items() if on and key != "archived"}
        self.assertEqual(set(jobs), enabled | {scheduler_service.BATCH_TICK_ID})
        self.assertEqual(str(jobs[scheduler_service.BATCH_TICK_ID].trigger), "interval[0:05:00]")
        self.assertEqual(str(jobs["hidream"].trigger), "cron[hour='4', minute='30']")
        self.assertEqual((next_hidream.hour, next_hidream.minute), (4, 30))
        # служебный тик не выдаётся за задачу в строке «активных задач»
        self.assertIn(f"активных задач: {len(enabled)} ", output[-1])
        self.assertNotIn(scheduler_service.BATCH_TICK_ID, output[-1])
        self.assertEqual(len(threads), 1)
        self.assertNotEqual(threads[0], threading.get_ident())   # не в потоке event loop

    def test_scheduler_really_fires_the_tick_without_blocking_the_loop(self):
        """Тик запускает сам APScheduler; пока тик «висит» в сети, event loop живёт."""
        ticks, heartbeats, seen = [], [], []

        def slow_tick():
            ticks.append(threading.get_ident())
            threading.Event().wait(0.6)          # как будто ждём ответа API

        class Collect(logging.Handler):
            def emit(self, record):
                seen.append(f"{record.levelname} {record.getMessage()}")

        async def scenario():
            service = scheduler_service.SchedulerService(task_manager=None)
            service.start()
            try:
                for _ in range(30):              # 1,5 секунды «работы панели»
                    await asyncio.sleep(0.05)
                    heartbeats.append(asyncio.get_running_loop().time())
            finally:
                service.shutdown()

        handler = Collect(level=logging.INFO)
        executor_log = logging.getLogger("apscheduler.executors.default")
        level = executor_log.level
        executor_log.addHandler(handler)
        executor_log.setLevel(logging.INFO)
        try:
            with mock.patch.object(scheduler_service, "BATCH_TICK_MINUTES", 0.5 / 60), \
                    mock.patch.object(scheduler_service, "get_generators", lambda: []), \
                    mock.patch.object(pb, "tick", slow_tick):
                asyncio.run(scenario())
        finally:
            executor_log.removeHandler(handler)
            executor_log.setLevel(level)
        self.assertGreaterEqual(len(ticks), 1)
        self.assertNotIn(threading.get_ident(), ticks)
        # цикл не замирал: между «ударами» не было пауз, сравнимых с длиной тика
        gaps = [later - earlier for earlier, later in zip(heartbeats, heartbeats[1:])]
        self.assertLess(max(gaps), 0.3)
        # В журнал не попали ни служебные строки о каждом срабатывании, ни ошибка
        # задания: сценарий гасит планировщик посреди тика, как перезапуск сервиса.
        self.assertEqual([line for line in seen if scheduler_service.BATCH_TICK_ID in line], [])

    def test_tick_lines_are_hidden_from_app_log_but_cron_lines_stay(self):
        quiet = scheduler_service._QuietBatchTick()

        def record(level, text):
            return logging.LogRecord("apscheduler.executors.default", level, "", 0,
                                     'Running job "%s"', (text,), None)

        tick_job = f"{scheduler_service.BATCH_TICK_ID} (trigger: interval[0:05:00])"
        self.assertFalse(quiet.filter(record(logging.INFO, tick_job)))
        self.assertTrue(quiet.filter(record(logging.WARNING, tick_job)))
        self.assertTrue(quiet.filter(record(logging.INFO, "SchedulerService._run (trigger: cron)")))

    def test_next_run_equals_scheduler_cron_trigger(self):
        from apscheduler.triggers.cron import CronTrigger
        for moment in (NOW, at(4, 30), at(4, 31), at(23, 59)):
            self.assertEqual(pb.next_run({"hour": 4, "minute": 30}, moment),
                             CronTrigger(hour=4, minute=30).get_next_fire_time(None, moment))
        self.assertEqual(pb.next_run({"hour": 4, "minute": 30}, at(4, 31)), at(4, 30, day=19))


if __name__ == "__main__":
    unittest.main(verbosity=2)
