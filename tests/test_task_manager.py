"""Статус запуска по записям журнала (webapp/task_manager.py).

    python -m unittest tests.test_task_manager
"""
import logging
import unittest

from webapp import task_manager


class GcNoiseTests(unittest.TestCase):
    def emit(self, name, level, message):
        manager = type("M", (), {})()
        manager.runs = {"r1": {"status": "running", "logs": [], "had_error": False}}
        handler = task_manager.LogCaptureHandler(manager)
        token = task_manager.current_run_id.set("r1")
        try:
            handler.emit(logging.LogRecord(name, level, __file__, 1, message, None, None))
        finally:
            task_manager.current_run_id.reset(token)
        return manager.runs["r1"]

    def test_asyncio_never_retrieved_is_logged_but_not_an_error(self):
        run = self.emit("asyncio", logging.ERROR, "Future exception was never retrieved")
        self.assertFalse(run["had_error"])
        self.assertEqual(len(run["logs"]), 1)

    def test_real_errors_still_count(self):
        self.assertTrue(self.emit("core.pipeline", logging.ERROR, "сбой")["had_error"])
        self.assertTrue(self.emit("asyncio", logging.ERROR, "Exception in callback")["had_error"])


if __name__ == "__main__":
    unittest.main()
