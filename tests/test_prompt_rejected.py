"""Отказ модерации генератора: новый промпт и повтор (core/pipeline.py, providers/image/yandex.py).

    .venv/bin/python -m unittest tests.test_prompt_rejected -v

Без сети: генератор, LLM, база, водяной знак и публикация подменены.
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from core import pipeline  # noqa: E402
from providers.image.base import PromptRejected  # noqa: E402
from providers.image.dalle import DalleProvider  # noqa: E402
from providers.image.yandex import YandexProvider  # noqa: E402

JOB = {"file_prefix": "t", "image": {"provider": "fake", "params": {}}, "watermark": {"enabled": False}}


class FakeProvider:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.prompts = []

    async def generate(self, prompt, params):
        self.prompts.append(prompt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class PipelineRejectTest(unittest.TestCase):
    def run_job(self, provider, job=JOB, fresh=("s2", "u2", "второй")):
        saved = []
        with mock.patch.object(pipeline, "_prepare_prompt", return_value=("s1", "u1", "первый")), \
             mock.patch.object(pipeline, "_render_and_generate", return_value=fresh) as regen, \
             mock.patch.object(pipeline.prompts_store, "get_prompt", return_value={"system": "s", "user": "u"}), \
             mock.patch.object(pipeline, "build_image_provider", return_value=provider), \
             mock.patch.object(pipeline.providers_store, "get_image_config", return_value={}), \
             mock.patch.object(pipeline, "_build_image_path", return_value=os.devnull), \
             mock.patch.object(pipeline, "save_to_database", side_effect=lambda **kw: saved.append(kw)), \
             mock.patch.object(pipeline, "_publish", new=mock.AsyncMock()):
            asyncio.run(pipeline._run_image_job("yandex", job))
        return regen, saved

    def test_rejected_prompt_is_rewritten_and_saved(self):
        provider = FakeProvider([PromptRejected("модерация"), b"png"])
        regen, saved = self.run_job(provider)
        self.assertEqual(provider.prompts, ["первый", "второй"])
        self.assertEqual(regen.call_count, 1)
        # В историю попадает текст, по которому картинка действительно нарисована.
        self.assertEqual(saved[0]["generated_prompt"], "второй")
        self.assertEqual(saved[0]["user_prompt"], "u2")

    def test_gives_up_after_limit(self):
        provider = FakeProvider([PromptRejected("1"), PromptRejected("2"), PromptRejected("3")])
        with self.assertRaises(PromptRejected):
            self.run_job(provider)
        self.assertEqual(len(provider.prompts), 3)

    def test_limit_from_job(self):
        provider = FakeProvider([PromptRejected("1")])
        with self.assertRaises(PromptRejected):
            self.run_job(provider, job=dict(JOB, prompt_rewrites_on_reject=0))
        self.assertEqual(len(provider.prompts), 1)

    def test_other_errors_are_not_retried(self):
        provider = FakeProvider([RuntimeError("сеть")])
        with self.assertRaises(RuntimeError):
            regen, _ = self.run_job(provider)
        self.assertEqual(len(provider.prompts), 1)


class YandexModerationTest(unittest.TestCase):
    def call(self, status, body):
        request = httpx.Request("POST", "https://ai.api.cloud.yandex.net/v1/images/generations")
        error = httpx.HTTPStatusError("x", request=request, response=httpx.Response(status, text=body, request=request))
        service = mock.Mock()
        service.return_value.generate_image.side_effect = error
        with mock.patch("services.yandex_service.YandexArtService", service):
            asyncio.run(YandexProvider("yandex", {}).generate("голые тополя", {}))

    def test_moderation_400_becomes_prompt_rejected(self):
        body = '{"error":{"message":"Я не могу сгенерировать это изображение. Давайте попробуем другую тему.","type":"invalid_request_error"}}'
        with self.assertRaises(PromptRejected):
            self.call(400, body)

    def test_other_400_stays_http_error(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.call(400, '{"error":{"message":"bad size"}}')

    def test_5xx_stays_http_error(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.call(500, "Я не могу сгенерировать")


class DalleModerationTest(unittest.TestCase):
    def call(self, status, body):
        transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
        provider = DalleProvider("dalle", {})
        with mock.patch.object(provider, "_client",
                               side_effect=lambda: httpx.AsyncClient(transport=transport)):
            return asyncio.run(provider.generate("нимфа у источника", {}))

    def test_safety_system_becomes_prompt_rejected(self):
        # Ответ 22.11.2026 (поле code в журнал не попало) и 14.11.2026.
        for body in (
            '{"error":{"message":"Your request was rejected by the safety system. If you believe '
            'this is an error, contact us. safety_violations=[sexual].",'
            '"type":"image_generation_user_error","param":null}}',
            '{"error":{"message":"Rejected.","type":"image_generation_user_error",'
            '"code":"moderation_blocked"}}',
        ):
            with self.assertRaises(PromptRejected):
                self.call(400, body)

    def test_other_400_stays_runtime_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.call(400, '{"error":{"message":"Invalid size","type":"invalid_request_error"}}')
        self.assertNotIsInstance(ctx.exception, PromptRejected)

    def test_success(self):
        self.assertEqual(self.call(200, '{"data":[{"b64_json":"cG5n"}]}'), b"png")


if __name__ == "__main__":
    unittest.main()
