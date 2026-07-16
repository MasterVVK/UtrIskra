"""Базовый интерфейс LLM-провайдера: генерация текстового промпта.

Провайдеры синхронные — пайплайн выполняется в отдельном потоке со своим
event loop, блокирующие вызовы допустимы.
"""


class LLMProvider:
    type = "base"

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config

    def generate(self, system_prompt: str, user_prompt: str, *,
                 temperature: float = 0.7, max_tokens: int = 8000) -> str:
        """Возвращает сгенерированный текст. Пустой ответ — ошибка (raise)."""
        raise NotImplementedError

    def health(self) -> tuple:
        """(ok: bool, сообщение) — быстрая проверка доступности без генерации."""
        return False, "проверка не реализована"

    def describe(self) -> str:
        """Краткое описание инстанса для списков в UI."""
        return self.config.get("model", "")


def build_llm_provider(name: str, config: dict) -> LLMProvider:
    """Фабрика по полю config["type"]."""
    from providers.llm.gemini import GeminiProvider
    from providers.llm.openai_compat import OpenAICompatProvider

    types = {"gemini": GeminiProvider, "openai": OpenAICompatProvider}
    provider_type = config.get("type")
    if provider_type not in types:
        raise ValueError(f"Неизвестный тип LLM-провайдера «{provider_type}» (инстанс {name})")
    return types[provider_type](name, config)
