"""Qwen Chat: повтор скачивания картинки с CDN (providers/image/qwen_chat.py).

    .venv/bin/python -m unittest tests.test_qwen_chat_download -v
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from providers.image import qwen_chat  # noqa: E402

URL = "https://cdn.example/output/x.png?key=secret"


def http_error(status):
    request = httpx.Request("GET", URL)
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(status, request=request))


def run(outcomes):
    calls = []

    async def fake(url):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with mock.patch.object(qwen_chat, "download_bytes", fake), \
         mock.patch.object(qwen_chat, "DOWNLOAD_DELAY", 0):
        try:
            return asyncio.run(qwen_chat._download_with_retries("qwen_chat", URL)), calls
        except Exception as exc:  # noqa: BLE001
            return exc, calls


class DownloadRetryTest(unittest.TestCase):
    def test_404_then_ok(self):
        with self.assertLogs(qwen_chat.logger, "WARNING") as logs:
            result, calls = run([http_error(404), http_error(404), b"png"])
        self.assertEqual(result, b"png")
        self.assertEqual(len(calls), 3)
        self.assertNotIn("secret", "\n".join(logs.output))

    def test_transport_error_and_5xx_are_retried(self):
        result, calls = run([httpx.ConnectError("reset"), http_error(502), b"png"])
        self.assertEqual(result, b"png")

    def test_403_is_not_retried(self):
        result, calls = run([http_error(403)])
        self.assertIsInstance(result, httpx.HTTPStatusError)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_limit(self):
        result, calls = run([http_error(404)] * qwen_chat.DOWNLOAD_ATTEMPTS)
        self.assertIsInstance(result, httpx.HTTPStatusError)
        self.assertEqual(len(calls), qwen_chat.DOWNLOAD_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
