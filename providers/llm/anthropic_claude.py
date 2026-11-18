"""LLM-провайдер Anthropic Claude (Messages API, официальный SDK).

Параметры инстанса (config):
  model        — id модели, по умолчанию claude-opus-5-5
  effort       — глубина рассуждения: low | medium | high | xhigh | max (default high)
  max_tokens   — потолок ответа ВМЕСТЕ с рассуждением (default 32000)
  api_key_env  — имя env-переменной с ключом (default ANTHROPIC_API_KEY)
  proxy        — ходить через PROXY_URL (default true: напрямую из РФ API недоступен)
  timeout      — секунд на запрос (default 600)
  batch        — заранее заготавливать промпты пакетом (Message Batches API,
                 вдвое дешевле); действует, только если инстанс первый в цепочке
                 задачи. Логика и расписание заготовки — core/prompt_batches.py
  batch_lead_minutes    — за сколько минут до ближайшего запуска слать пакет (120)
  batch_horizon_minutes — на сколько минут вперёд набирать запуски в пакет (360)

Особенности Claude Opus 5.5, из-за которых провайдер не повторяет остальные:
  * temperature / top_p API отвергает с 400 — параметр `temperature` из задачи
    сюда не передаётся вовсе. Разнообразие задаётся самим промптом (seed,
    категория, номер концепции), а не сэмплингом.
  * Рассуждение включено всегда и расходует тот же max_tokens, что и ответ,
    поэтому потолок берётся из конфига инстанса, а не общий пайплайновый 8000:
    с ним ответ мог бы оборваться, не начавшись.
  * Запрос идёт потоком — так длинное рассуждение не упирается в HTTP-таймаут.
  * Включён серверный fallback: если классификатор безопасности отклонит
    запрос, API сам повторит его на другой модели внутри того же вызова.

Пакетный путь (submit_batch / batch_status / batch_results) шлёт те же model,
max_tokens и effort, что и синхронный, — общая часть собирается в
_request_params. Отличия пакета: `stream` и `fallbacks` в нём запрещены, так
что отказ классификатора остаётся отказом — заготовки не будет, и задача
пойдёт обычной цепочкой (где fallback есть).
"""
import logging
import os

import anthropic
from anthropic import DefaultHttpxClient
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Вызовы пакетного API — короткие служебные запросы (создать, спросить статус,
# скачать результаты), генерации в них нет: 600 секунд из конфига им ни к чему,
# а тик заготовки (раз в 5 минут) не должен висеть на недоступной сети.
BATCH_TIMEOUT = 30.0


class AnthropicProvider(LLMProvider):
    type = "anthropic"

    def __init__(self, name, config):
        super().__init__(name, config)
        self.model = config.get("model") or DEFAULT_MODEL
        self.effort = config.get("effort", "high")
        self.max_tokens = int(config.get("max_tokens", 32000))
        self.timeout = float(config.get("timeout", 600))

    def describe(self):
        return f"{self.model} · effort {self.effort}"

    def _client(self, **overrides) -> anthropic.Anthropic:
        key = os.getenv(self.config.get("api_key_env") or "ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError(f"LLM «{self.name}»: не задан ключ "
                               f"({self.config.get('api_key_env') or 'ANTHROPIC_API_KEY'} в .env)")
        kwargs = {"api_key": key, "timeout": self.timeout}
        if self.config.get("proxy", True):
            proxy_url = os.getenv("PROXY_URL", "")
            if proxy_url:
                kwargs["http_client"] = DefaultHttpxClient(proxy=proxy_url)
        kwargs.update(overrides)
        return anthropic.Anthropic(**kwargs)

    def _request_params(self, system_prompt, user_prompt) -> dict:
        """Тело запроса, общее для синхронного и пакетного путей.

        Собирается в одном месте, чтобы model / max_tokens / effort не разошлись:
        заготовленный пакетом текст должен быть тем же, что дал бы обычный вызов.
        temperature / top_p сюда не попадают никогда — API отвергает их с 400.
        """
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": user_prompt}],
            "output_config": {"effort": self.effort},
        }
        if system_prompt:
            params["system"] = system_prompt
        return params

    def _api_error(self, exc) -> RuntimeError:
        """Ошибка SDK → понятная строка для журнала."""
        if isinstance(exc, anthropic.AuthenticationError):
            return RuntimeError(f"LLM «{self.name}»: ключ отклонён — {exc.message}")
        if isinstance(exc, anthropic.RateLimitError):
            return RuntimeError(f"LLM «{self.name}»: превышен лимит запросов — {exc.message}")
        if isinstance(exc, anthropic.APIStatusError):
            return RuntimeError(f"LLM «{self.name}»: HTTP {exc.status_code} — {exc.message}")
        return RuntimeError(f"LLM «{self.name}»: нет связи с API — {exc}")

    def _message_text(self, message) -> str:
        """Текст ответа; отказ, обрыв по max_tokens и пустой ответ — ошибка.

        stop_reason проверяется до чтения content: у отказа и у оборванного
        рассуждения текста либо нет, либо он не тот, что просили.
        """
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None)
            raise RuntimeError(f"LLM «{self.name}»: модель отклонила запрос"
                               f"{f' (категория {category})' if category else ''}")
        if message.stop_reason == "max_tokens":
            raise RuntimeError(f"LLM «{self.name}»: ответ оборван по max_tokens={self.max_tokens}")
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if not text:
            raise RuntimeError(f"LLM «{self.name}»: пустой ответ (stop_reason={message.stop_reason})")
        return text

    def generate(self, system_prompt, user_prompt, *, temperature=0.7, max_tokens=8000):
        params = {
            **self._request_params(system_prompt, user_prompt),
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }

        logger.info("LLM «%s»: запрос к Anthropic (модель %s, effort %s)",
                    self.name, self.model, self.effort)
        try:
            with self._client() as client:
                with client.beta.messages.stream(**params) as stream:
                    message = stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise self._api_error(exc) from exc

        text = self._message_text(message)
        usage = message.usage
        logger.info("LLM «%s»: ответ от %s, токены: вход %s, выход %s",
                    self.name, message.model, usage.input_tokens, usage.output_tokens)
        return text

    # ------------------------------------------------------- пакетный API

    def submit_batch(self, items) -> str:
        """Отправляет пакет; items — [(custom_id, system_prompt, user_prompt)]. Возвращает id пакета.

        Без авто-повторов SDK: создание пакета не идемпотентно, и повтор после
        потерянного ответа создал бы второй оплачиваемый пакет. Повторяет тик
        заготовки — следующим проходом.
        """
        requests = [
            Request(custom_id=custom_id,
                    params=MessageCreateParamsNonStreaming(
                        **self._request_params(system_prompt, user_prompt)))
            for custom_id, system_prompt, user_prompt in items
        ]
        try:
            with self._client(timeout=BATCH_TIMEOUT, max_retries=0) as client:
                batch = client.messages.batches.create(requests=requests)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise self._api_error(exc) from exc
        return batch.id

    def batch_status(self, batch_id: str) -> dict:
        """Состояние пакета: {"status": in_progress | canceling | ended | not_found, ...}."""
        try:
            with self._client(timeout=BATCH_TIMEOUT) as client:
                batch = client.messages.batches.retrieve(batch_id)
        except anthropic.NotFoundError:
            return {"status": "not_found", "processing": 0, "ended_at": None}
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise self._api_error(exc) from exc
        return {
            "status": batch.processing_status,
            "processing": batch.request_counts.processing,
            "ended_at": batch.ended_at.isoformat(timespec="seconds") if batch.ended_at else None,
        }

    def batch_results(self, batch_id: str) -> dict:
        """Результаты завершённого пакета: custom_id → {"text", "model", "usage"} или {"error"}.

        Результаты приходят в произвольном порядке — сопоставлять только по custom_id.
        """
        outcomes = {}
        try:
            with self._client(timeout=BATCH_TIMEOUT) as client:
                for entry in client.messages.batches.results(batch_id):
                    outcomes[entry.custom_id] = self._batch_outcome(entry.result)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise self._api_error(exc) from exc
        return outcomes

    def _batch_outcome(self, result) -> dict:
        if result.type == "succeeded":
            message = result.message
            try:
                text = self._message_text(message)
            except RuntimeError as exc:  # отказ / обрыв / пусто — это не заготовка
                return {"error": str(exc)}
            return {"text": text, "model": message.model,
                    "usage": {"input_tokens": message.usage.input_tokens,
                              "output_tokens": message.usage.output_tokens}}
        if result.type == "errored":
            # в SDK ошибка вложена: ErrorResponse.error → объект с type и message
            error = getattr(result.error, "error", None) or result.error
            return {"error": f"ошибка API ({getattr(error, 'type', '?')}): "
                             f"{getattr(error, 'message', '')}".rstrip(": ")}
        if result.type == "expired":
            return {"error": "запрос просрочен: пакет не успел обработаться за 24 часа"}
        if result.type == "canceled":
            return {"error": "запрос отменён"}
        return {"error": f"неизвестный тип результата «{result.type}»"}

    def health(self):
        try:
            with self._client() as client:
                model = client.models.retrieve(self.model)
            return True, f"{model.display_name} доступна"
        except anthropic.AuthenticationError:
            return False, "неверный или отсутствующий API-ключ"
        except anthropic.NotFoundError:
            return False, f"модель «{self.model}» не найдена"
        except Exception as exc:
            return False, str(exc)[:200]
