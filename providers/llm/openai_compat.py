"""Универсальный OpenAI-совместимый LLM-провайдер (/chat/completions).

Покрывает self-hosted и облачные endpoint'ы: Qwen2API, Ollama, vLLM,
LM Studio, llama.cpp-server, OpenRouter, OpenAI.

Конфиг инстанса:
  base_url     — например "http://192.168.0.58:3001/v1"
  model        — имя модели endpoint'а
  api_key_env  — имя env-переменной с ключом (опционально)
  timeout      — секунды (default 300; thinking-модели считают долго)
  proxy        — использовать SOCKS5 из PROXY_URL (default false — обычно локальная сеть)
"""
import logging
import os

import httpx
from httpx_socks import SyncProxyTransport

from providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _resolve_key(env_name: str) -> str:
    """Ключ из env; если переменная не задана — одноимённый атрибут config.py
    (там живут дефолтные цепочки вида FALLBACK_LLM_KEY -> QWEN_CHAT_API_KEY)."""
    if not env_name:
        return ""
    value = os.getenv(env_name, "")
    if value:
        return value
    import config as app_config
    return str(getattr(app_config, env_name, "") or "")


class OpenAICompatProvider(LLMProvider):
    type = "openai"

    def __init__(self, name, config):
        super().__init__(name, config)
        self.base_url = config.get("base_url", "").rstrip("/")
        self.model = config.get("model", "")
        self.api_key = _resolve_key(config.get("api_key_env", ""))
        self.timeout = float(config.get("timeout", 300))

    def describe(self):
        return f"{self.model} @ {self.base_url}"

    def _client(self) -> httpx.Client:
        kwargs = {"timeout": httpx.Timeout(self.timeout)}
        if self.config.get("proxy", False):
            proxy_url = os.getenv("PROXY_URL", "")
            if proxy_url:
                kwargs["transport"] = SyncProxyTransport.from_url(proxy_url)
        return httpx.Client(**kwargs)

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def generate(self, system_prompt, user_prompt, *, temperature=0.7, max_tokens=8000):
        if not self.base_url or not self.model:
            raise RuntimeError(f"LLM «{self.name}»: не заданы base_url/model")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        logger.info("LLM «%s»: запрос к %s (модель %s)", self.name, self.base_url, self.model)
        with self._client() as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={"model": self.model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens, "stream": False},
            )
            response.raise_for_status()
            data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not text.strip():
            raise RuntimeError(f"LLM «{self.name}»: пустой ответ модели {self.model}")
        return text

    def health(self):
        if not self.base_url:
            return False, "не задан base_url"
        try:
            with self._client() as client:
                response = client.get(f"{self.base_url}/models",
                                      headers=self._headers(), timeout=10)
            if response.status_code == 200:
                models = [m.get("id") for m in response.json().get("data", [])]
                if self.model in models:
                    return True, f"доступен, модель {self.model} на месте"
                return True, f"доступен ({len(models)} моделей; {self.model} не в списке)"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)
