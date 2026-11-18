"""OpenAI-совместимый провайдер: проверка пула по health_url перед запросом.

    .venv/bin/python -m unittest tests.test_llm_pool_check -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers.llm.openai_compat import OpenAICompatProvider  # noqa: E402

CONFIG = {"type": "openai", "base_url": "http://x/v1", "model": "m", "health_url": "http://h/health"}


def provider(config=CONFIG):
    return OpenAICompatProvider("qwen-fallback", dict(config))


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class FakeClient:
    """Подмена httpx.Client: считает отправленные запросы к /chat/completions."""
    posts = 0

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **kw):
        FakeClient.posts += 1
        return FakeResponse({"choices": [{"message": {"content": "текст"}}]})


class PoolCheckTest(unittest.TestCase):
    def setUp(self):
        FakeClient.posts = 0

    def generate(self, health, config=CONFIG):
        with mock.patch("providers.llm.openai_compat.httpx.Client", FakeClient), \
             mock.patch("providers.llm.openai_compat.httpx.get", side_effect=health) as get:
            return provider(config).generate("s", "u"), get

    def test_empty_pool_is_not_called(self):
        with self.assertRaisesRegex(RuntimeError, "нет свободных"):
            self.generate(lambda *a, **kw: FakeResponse({"pool": 8, "free": 0}))
        self.assertEqual(FakeClient.posts, 0)

    def test_free_pool_is_called(self):
        text, _ = self.generate(lambda *a, **kw: FakeResponse({"pool": 8, "free": 3}))
        self.assertEqual(text, "текст")
        self.assertEqual(FakeClient.posts, 1)

    def test_unreachable_health_does_not_block(self):
        def boom(*a, **kw):
            raise OSError("нет связи")
        text, _ = self.generate(boom)
        self.assertEqual(text, "текст")

    def test_without_health_url_no_check(self):
        config = {k: v for k, v in CONFIG.items() if k != "health_url"}
        text, get = self.generate(lambda *a, **kw: FakeResponse({"free": 0}), config)
        self.assertEqual(text, "текст")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
