"""Повторы провайдера images-api: запасная модель и повторное ожидание VRAM.

    .venv/bin/python -m unittest tests.test_images_api_retry -v
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.image.images_api import ImagesApiProvider, TaskFailed  # noqa: E402


def run(config, outcomes):
    """Прогон generate с подменённым _run_task; возвращает (результат|исключение, модели)."""
    calls = []

    async def fake(self, payload):
        calls.append(payload["model"])
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    provider = ImagesApiProvider("t", dict({"base_url": "http://x", "params": []}, **config))
    with mock.patch.object(ImagesApiProvider, "_run_task", fake):
        try:
            return asyncio.run(provider.generate("p", {})), calls
        except Exception as exc:  # noqa: BLE001
            return exc, calls


def vram():
    return TaskFailed("нет памяти", "vram_unavailable")


class RetryTest(unittest.TestCase):
    def test_no_rounds_by_default(self):
        result, calls = run({"model": "m"}, [vram()])
        self.assertIsInstance(result, TaskFailed)
        self.assertEqual(calls, ["m"])

    def test_vram_rounds_resubmit_same_model(self):
        result, calls = run({"model": "m", "vram_wait_rounds": 5}, [vram(), vram(), b"png"])
        self.assertEqual(result, b"png")
        self.assertEqual(calls, ["m", "m", "m"])

    def test_vram_rounds_are_limited(self):
        result, calls = run({"model": "m", "vram_wait_rounds": 2}, [vram(), vram(), vram()])
        self.assertIsInstance(result, TaskFailed)
        self.assertEqual(len(calls), 3)

    def test_oom_during_generation_is_resubmitted(self):
        result, calls = run({"model": "m", "vram_wait_rounds": 2},
                            [TaskFailed("CUDA out of memory", "vram_oom"), b"png"])
        self.assertEqual(result, b"png")
        self.assertEqual(calls, ["m", "m"])

    def test_other_errors_are_not_resubmitted(self):
        result, calls = run({"model": "m", "vram_wait_rounds": 5},
                            [TaskFailed("неверный размер", "invalid_request")])
        self.assertIsInstance(result, TaskFailed)
        self.assertEqual(calls, ["m"])

    def test_backend_error_resubmitted_once(self):
        not_resident = TaskFailed("model m is not resident (current: None)", "backend_error")
        result, calls = run({"model": "m"}, [not_resident, b"png"])
        self.assertEqual(result, b"png")
        self.assertEqual(calls, ["m", "m"])

        result, calls = run({"model": "m"}, [not_resident, not_resident])
        self.assertIsInstance(result, TaskFailed)
        self.assertEqual(len(calls), 2)

        result, calls = run({"model": "m", "backend_error_retries": 0}, [not_resident])
        self.assertIsInstance(result, TaskFailed)
        self.assertEqual(calls, ["m"])

    def test_fallback_first_then_rounds_on_last_model(self):
        config = {"model": "full", "fallback_models": {"full": "small"}, "vram_wait_rounds": 1}
        result, calls = run(config, [vram(), vram(), b"png"])
        self.assertEqual(result, b"png")
        self.assertEqual(calls, ["full", "small", "small"])


if __name__ == "__main__":
    unittest.main()
