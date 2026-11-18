"""Вечерняя заготовка промптов (pregen): Qwen4 вечером, пакет Opus закрывает пропуски.

    .venv/bin/python -m unittest tests.test_prompt_pregen -v

Окружение (временные состояние и база промптов, задачи, расписание, заглушка
пакетов Anthropic) — из tests/test_prompt_batches.py. Qwen4 подменён: generate
синхронно возвращает текст или бросает ошибку по заданному сценарию.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import prompt_batches as pb  # noqa: E402
from providers.llm.openai_compat import OpenAICompatProvider  # noqa: E402
from tests.test_prompt_batches import BatchTestCase, at, job, providers  # noqa: E402

EVENING = at(19, 40)             # 18.11, после сброса квоты
TRIGGER = at(19, 35)
# Запуски до 09:40 следующего дня (горизонт 14 ч): own_llm (свой провайдер — gemini),
# off, archived и bestof не участвуют.
TOMORROW = ["dalle", "hidream", "late", "mjvideo", "qwen", "zimage"]


class PregenTestCase(BatchTestCase):
    def setUp(self):
        super().setUp()
        self.trigger_path = os.path.join(self.tmp.name, "quota", "evening-start")
        self.done_path = os.path.join(self.tmp.name, "quota", "utriskra-done")
        self.providers = self.pregen_providers()
        self.calls = []
        self.fail_on = set()      # номера вызовов (с 1), которые бросают ошибку
        test = self

        def fake_generate(provider, system, user, *, temperature=0.7, max_tokens=8000):
            test.calls.append((system, user, temperature))
            if len(test.calls) in test.fail_on:
                raise RuntimeError("Server error '502 Bad Gateway'")
            return f"  текст Qwen4 №{len(test.calls)}  "

        patcher = mock.patch.object(OpenAICompatProvider, "generate", fake_generate)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pregen_providers(self, pregen=True, **extra):
        data = providers()
        data["llm"]["qwen-fallback"].update(
            pregen=pregen, pregen_trigger_file=self.trigger_path,
            pregen_done_file=self.done_path, **extra)
        return data

    def trigger(self, moment=TRIGGER):
        os.makedirs(os.path.dirname(self.trigger_path), exist_ok=True)
        with open(self.trigger_path, "w") as file:
            file.write(moment.isoformat() + "\n")

    def done(self):
        with open(self.done_path) as file:
            return json.load(file)


class PregenTests(PregenTestCase):
    def test_trigger_runs_one_request_per_run_and_reports(self):
        self.trigger()
        summary = pb.pregen_check(EVENING, background=False)
        self.assertEqual((summary["ok"], summary["failed"], summary["reason"]), (6, 0, None))
        self.assertEqual(len(self.calls), 6)
        drafts = self.drafts("ready")
        self.assertEqual(sorted(drafts), TOMORROW)
        hidream = drafts["hidream"]
        self.assertEqual(hidream["provider"], "qwen-fallback")
        self.assertEqual(pb._parse(hidream["run_at"]), at(4, 30, day=19))
        self.assertTrue(hidream["text"].startswith("текст Qwen4"))   # без пробелов по краям
        self.assertIn("date=19 November 2026", hidream["user"])      # дата запуска, не вечера
        self.assertEqual(hidream["prompt_id"], self.prompt_id("hidream"))
        # первый — ближайший запуск
        self.assertIn("user hidream", self.calls[0][1])
        # итог для другой стороны: формат протокола, started не раньше триггера
        done = self.done()
        self.assertEqual({k: done[k] for k in ("ok", "failed", "reason")},
                         {"ok": 6, "failed": 0, "reason": None})
        self.assertGreaterEqual(pb._parse(done["started"]), TRIGGER)
        self.assertGreaterEqual(pb._parse(done["finished"]), pb._parse(done["started"]))

    def test_same_trigger_fires_once_new_trigger_fires_again(self):
        self.trigger()
        pb.pregen_check(EVENING, background=False)
        self.assertEqual(pb.pregen_check(at(19, 41), background=False), {})
        self.assertEqual(len(self.calls), 6)
        # следующий вечер: новый триггер, запуски 20.11
        self.trigger(at(19, 35, day=19))
        summary = pb.pregen_check(at(19, 40, day=19), background=False)
        self.assertEqual(summary["ok"], 6)
        self.assertEqual(len(self.calls), 12)

    def test_skipped_jobs_get_no_pregen_and_stay_for_opus(self):
        """pregen_skip: задача (у нас minimax — слишком длинный ответ для Qwen4) вечером
        пропускается, остальные заготавливаются, её запуск закрывает пакет Opus."""
        self.providers = self.pregen_providers(pregen_skip=["hidream"])
        self.trigger()
        summary = pb.pregen_check(EVENING, background=False)
        self.assertEqual(summary["ok"], 5)
        self.assertNotIn("hidream", self.drafts("ready"))
        self.assertFalse(any("user hidream" in call[1] for call in self.calls))
        pb.tick(at(2, 30, day=19))               # до hidream в 04:30 — lead 120 мин
        self.assertIn("hidream", self.sent_jobs())

    def test_old_or_missing_trigger_does_nothing(self):
        self.assertEqual(pb.pregen_check(EVENING, background=False), {})
        self.trigger(at(15, 0))                  # старше 3 часов
        self.assertEqual(pb.pregen_check(EVENING, background=False), {})
        self.assertEqual(self.calls, [])
        self.assertFalse(os.path.exists(self.done_path))

    def test_without_flag_trigger_is_ignored(self):
        self.providers = self.pregen_providers(pregen=False)
        self.trigger()
        self.assertEqual(pb.pregen_check(EVENING, background=False), {})
        self.assertEqual(self.calls, [])

    def test_first_error_stops_and_opus_batch_covers_the_rest(self):
        self.fail_on = {2}
        self.trigger()
        summary = pb.pregen_check(EVENING, background=False)
        self.assertEqual((summary["ok"], summary["failed"]), (1, 1))
        self.assertIn("502", summary["reason"])
        self.assertEqual(len(self.calls), 2)     # после ошибки — ни одного запроса
        self.assertEqual(sorted(self.drafts("ready")), ["hidream"])
        self.assertEqual(self.done()["failed"], 1)
        # ночью пакет Opus заказывает только незакрытые запуски: в 02:30 ещё рано
        # (ближайший незакрытый — zimage в 05:00, до него больше lead 120 мин)…
        self.assertEqual(pb.tick(at(2, 30, day=19))["submitted"], [])
        # …в 03:00 — пакет на окно до 09:00 без hidream (закрыт заготовкой Qwen4)
        pb.tick(at(3, 0, day=19))
        self.assertEqual(self.sent_jobs(), ["dalle", "late", "mjvideo", "qwen", "zimage"])

    def test_full_pregen_leaves_nothing_for_opus(self):
        self.trigger()
        pb.pregen_check(EVENING, background=False)
        self.assertEqual(pb.tick(at(2, 30, day=19))["submitted"], [])
        self.assertEqual(self.batches.created, [])

    def test_run_takes_pregen_draft_before_batch_draft(self):
        self.trigger()
        pb.pregen_check(EVENING, background=False)
        # тот же запуск закрыт и пакетом Opus (например, отправлен вручную)
        pb.submit_forced(["hidream"], at(2, 30, day=19))
        self.assertEqual(self.batches.created, [])   # уже закрыт заготовкой Qwen4
        draft = pb.take_draft("hidream", job(max_theme=50),
                              {"id": self.prompt_id("hidream")}, at(4, 30, day=19))
        self.assertEqual(draft["provider"], "qwen-fallback")
        self.assertTrue(draft["batch_id"].startswith("pregen-"))
        self.assertEqual(self.drafts()["hidream"]["status"], "used")

    def test_job_without_pregen_in_chain_is_skipped(self):
        self.providers["llm_chain"] = ["opus", "gemini"]
        self.trigger()
        summary = pb.pregen_check(EVENING, background=False)
        self.assertEqual(summary["ok"], 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.done()["ok"], 0)     # отчёт пишется и тогда: другая сторона ждёт

    def test_changed_prompt_retires_pregen_draft(self):
        self.trigger()
        pb.pregen_check(EVENING, background=False)
        from core import prompts as prompts_store
        prompts_store.save_prompt("hidream", "новый system", "новый user {random_seed}")
        draft = pb.take_draft("hidream", job(max_theme=50),
                              {"id": self.prompt_id("hidream")}, at(4, 30, day=19))
        self.assertIsNone(draft)

    def test_background_mode_returns_at_once(self):
        self.trigger()
        with mock.patch.object(pb.threading, "Thread") as thread:
            result = pb.pregen_check(EVENING)
        self.assertEqual(result, {"trigger": TRIGGER.isoformat(timespec="seconds")})
        thread.return_value.start.assert_called_once()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
