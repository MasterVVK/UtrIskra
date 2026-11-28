"""Gemini: ключ уходит заголовком x-goog-api-key, а не `?key=` в URL (его пишет журнал httpx).

    .venv/bin/python -m unittest tests.test_gemini_key -v
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from providers.image import gemini_image  # noqa: E402
from providers.llm import gemini  # noqa: E402

KEYS = "k-first,k-second"


def answer(request):
    if request.method == "GET":
        return httpx.Response(200, json={})
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})


class GeminiKeyTest(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return answer(request)

        self.transport = httpx.MockTransport(handler)
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEYS": KEYS})
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self, key):
        request = self.requests[-1]
        self.assertEqual(request.headers.get("x-goog-api-key"), key)
        self.assertNotIn("key", request.url.params)
        self.assertNotIn(key, str(request.url))

    def test_llm_generate_and_health(self):
        provider = gemini.GeminiProvider("gemini", {"proxy": False})
        with mock.patch.object(provider, "_client", lambda: httpx.Client(transport=self.transport)):
            self.assertEqual(provider.generate("s", "u"), "ok")
            self.check("k-first")
            self.assertTrue(provider.health()[0])
            self.check("k-first")

    def test_image_health(self):
        provider = gemini_image.GeminiImageProvider("gemini_image", {})
        real = httpx.AsyncClient

        def client(**kwargs):
            return real(transport=self.transport, **kwargs)

        with mock.patch.object(gemini_image.httpx, "AsyncClient", client):
            self.assertTrue(asyncio.run(provider.health())[0])
        self.check("k-first")


if __name__ == "__main__":
    unittest.main()
