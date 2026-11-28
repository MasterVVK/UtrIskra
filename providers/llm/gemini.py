"""Gemini-провайдер: ротация API-ключей, SOCKS5-прокси, модель из конфига.

Конфиг инстанса:
  model      — например "gemini-3.5-flash"
  keys_env   — имя env-переменной со списком ключей через запятую (default GEMINI_API_KEYS)
  proxy      — использовать SOCKS5 из PROXY_URL (default true)
  timeout    — секунды (default 120)

В отличие от старого services/gemini_service.py: без встроенного fallback
(цепочку провайдеров собирает пайплайн), с logging вместо print, при полном
отказе поднимает исключение, а не возвращает пустую строку.
"""
import logging
import os
import time

import httpx
from httpx_socks import SyncProxyTransport

from providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_503_RETRIES = 3
RETRY_DELAY_SEC = 10


def key_header(key: str) -> dict:
    """Ключ — заголовком, не `?key=` в URL: httpx пишет URL запроса в журнал (INFO)."""
    return {"x-goog-api-key": key}


class GeminiProvider(LLMProvider):
    type = "gemini"

    def __init__(self, name, config):
        super().__init__(name, config)
        self.model = config.get("model", "gemini-3.5-flash")
        keys_env = config.get("keys_env", "GEMINI_API_KEYS")
        self.api_keys = [k.strip() for k in os.getenv(keys_env, "").split(",") if k.strip()]
        self.timeout = float(config.get("timeout", 120))
        self._key_index = 0

    def _client(self) -> httpx.Client:
        kwargs = {"timeout": httpx.Timeout(self.timeout)}
        if self.config.get("proxy", True):
            proxy_url = os.getenv("PROXY_URL", "")
            if proxy_url:
                kwargs["transport"] = SyncProxyTransport.from_url(proxy_url)
        return httpx.Client(**kwargs)

    def _next_key(self):
        self._key_index = (self._key_index + 1) % len(self.api_keys)

    def generate(self, system_prompt, user_prompt, *, temperature=0.7, max_tokens=8000):
        if not self.api_keys:
            raise RuntimeError(f"LLM «{self.name}»: нет ключей ({self.config.get('keys_env', 'GEMINI_API_KEYS')})")
        url = f"{BASE_URL}/{self.model}:generateContent"
        payload = {
            "generationConfig": {"temperature": temperature, "max_output_tokens": max_tokens},
            "contents": [{"parts": [{"text": system_prompt}, {"text": user_prompt}]}],
        }
        with self._client() as client:
            for _ in range(len(self.api_keys)):
                key = self.api_keys[self._key_index]
                retries = 0
                while retries < MAX_503_RETRIES:
                    try:
                        response = client.post(url, headers=key_header(key), json=payload)
                    except Exception as exc:
                        retries += 1
                        logger.warning("LLM «%s»: сетевая ошибка (%s), попытка %d/%d",
                                       self.name, exc, retries, MAX_503_RETRIES)
                        time.sleep(RETRY_DELAY_SEC)
                        continue
                    if response.status_code == 200:
                        data = response.json()
                        text = (data.get("candidates", [{}])[0].get("content", {})
                                .get("parts", [{}])[0].get("text", ""))
                        if not text.strip():
                            raise RuntimeError(f"LLM «{self.name}»: пустой ответ модели {self.model}")
                        return text
                    if response.status_code == 503:
                        retries += 1
                        logger.warning("LLM «%s»: модель перегружена (503), попытка %d/%d",
                                       self.name, retries, MAX_503_RETRIES)
                        time.sleep(RETRY_DELAY_SEC)
                        continue
                    if response.status_code == 429:
                        logger.warning("LLM «%s»: ключ #%d исчерпан (429), переключаюсь",
                                       self.name, self._key_index + 1)
                        self._next_key()
                        break
                    if response.status_code == 400 and "API_KEY_INVALID" in response.text:
                        logger.error("LLM «%s»: ключ #%d невалиден, пропускаю",
                                     self.name, self._key_index + 1)
                        self._next_key()
                        break
                    raise RuntimeError(f"LLM «{self.name}»: ошибка API {response.status_code}: "
                                       f"{response.text[:300]}")
                else:
                    logger.warning("LLM «%s»: повторы 503 исчерпаны, следующий ключ", self.name)
                    self._next_key()
        raise RuntimeError(f"LLM «{self.name}»: все ключи ({len(self.api_keys)}) недоступны")

    def health(self):
        if not self.api_keys:
            return False, "нет ключей"
        try:
            with self._client() as client:
                response = client.get(f"{BASE_URL}/{self.model}",
                                      headers=key_header(self.api_keys[self._key_index]),
                                      timeout=15)
            if response.status_code == 200:
                return True, f"модель {self.model} доступна, ключей: {len(self.api_keys)}"
            return False, f"HTTP {response.status_code}: {response.text[:120]}"
        except Exception as exc:
            return False, str(exc)
