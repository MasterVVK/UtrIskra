"""Публикация в Telegram: повтор JPEG-копией после IMAGE_PROCESS_FAILED (core/publisher.py).

    .venv/bin/python -m unittest tests.test_publisher -v

Без сети: бот подменён, картинка — маленький PNG во временном каталоге.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from core import publisher  # noqa: E402

FAILED = RuntimeError("Telegram server says - Bad Request: IMAGE_PROCESS_FAILED")


class FakeBot:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.sent = []          # (путь, существовал ли файл в момент отправки)
        self.session = mock.Mock(close=mock.AsyncMock())

    async def send_photo(self, chat_id, photo, caption=None):
        self.sent.append((photo.path, os.path.exists(photo.path)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return mock.Mock(message_id=1)


class RetryAsJpegTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = os.path.join(self.tmp.name, "pic.png")
        Image.new("RGB", (64, 36), (200, 120, 40)).save(self.png)

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, outcomes, retries=3):
        bot = FakeBot(outcomes)
        with mock.patch.object(publisher, "Bot", return_value=bot), \
             mock.patch.object(publisher, "AiohttpSession"), \
             mock.patch.object(publisher, "_resolve_destination", return_value=("t", "chat", False)), \
             mock.patch.object(publisher, "RETRY_DELAY", 0):
            asyncio.run(publisher.publish_media(self.png, retries=retries, caption="c"))
        return bot

    def test_image_process_failed_switches_to_jpeg(self):
        bot = self.publish([FAILED, "ok"])
        (first, _), (second, existed) = bot.sent
        self.assertEqual(first, self.png)
        self.assertTrue(second.endswith(".jpg") and existed)
        self.assertFalse(os.path.exists(second), "временная копия должна удаляться")
        self.assertTrue(os.path.exists(self.png), "оригинал не трогаем")

    def test_copy_is_made_once(self):
        bot = self.publish([FAILED, FAILED, "ok"])
        paths = [path for path, _ in bot.sent]
        self.assertEqual(paths[1], paths[2])

    def test_other_errors_retry_same_file(self):
        bot = self.publish([RuntimeError("timeout"), "ok"])
        self.assertEqual([path for path, _ in bot.sent], [self.png, self.png])

    def test_last_attempt_raises(self):
        with self.assertRaises(RuntimeError):
            self.publish([FAILED, FAILED], retries=1)


if __name__ == "__main__":
    unittest.main()
