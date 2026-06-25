import time
import httpx
from httpx_socks import SyncProxyTransport
from config import (GEMINI_API_KEYS, PROXY_URL,
                    FALLBACK_LLM_URL, FALLBACK_LLM_KEY, FALLBACK_LLM_MODEL)

# Параметры повторов при ошибке 503 (перегрузка модели)
MAX_503_RETRIES = 3        # было 20
RETRY_DELAY_SEC = 10       # было 50


class GeminiService:
    """Класс для взаимодействия с Gemini Pro через SOCKS5-прокси и балансировку ключей."""

    def __init__(self, timeout: int = 120):
        if not GEMINI_API_KEYS:
            raise ValueError("GEMINI_API_KEYS отсутствуют. Проверьте файл config.py.")
        if not PROXY_URL:
            raise ValueError("PROXY_URL отсутствует. Проверьте файл config.py.")
        self.api_keys = GEMINI_API_KEYS
        self.current_key_index = 0
        self.proxy_url = PROXY_URL
        # Настройка прокси
        self.transport = SyncProxyTransport.from_url(self.proxy_url)
        self.client = httpx.Client(transport=self.transport, timeout=httpx.Timeout(timeout))

    @property
    def current_key(self) -> str:
        """Возвращает текущий API-ключ."""
        return self.api_keys[self.current_key_index]

    def switch_to_next_key(self):
        """Переключает на следующий ключ."""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        print(f"[INFO] Переключение на следующий ключ: {self.current_key}")

    def generate_prompt(self, system_prompt: str, user_prompt: str, temperature: float = 0.9,
                        max_output_tokens: int = 8000) -> str:
        """
        Генерирует ответ на основе промпта.
        :param system_prompt: Системное сообщение.
        :param user_prompt: Запрос пользователя.
        :param temperature: Температура генерации.
        :param max_output_tokens: Максимальное количество токенов.
        :return: Ответ в текстовом виде.
        """
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        # Пытаемся использовать ключи по очереди
        for _ in range(len(self.api_keys)):
            retries = 0  # Счетчик повторных попыток при статусе 503
            while retries < MAX_503_RETRIES:
                try:
                    response = self.client.post(
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent",
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp-02-05:generateContent",
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent",
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent",
                        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent",
                        # "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",

                        params={"key": self.current_key},
                        headers={"Content-Type": "application/json"},
                        json={
                            "generationConfig": generation_config,
                            "contents": [{"parts": [{"text": system_prompt}, {"text": user_prompt}]}],
                        },
                    )
                except Exception as e:
                    retries += 1
                    print(
                        f"[WARNING] Сетевая ошибка ({e}). Повтор через {RETRY_DELAY_SEC} секунд... (Попытка {retries} из {MAX_503_RETRIES})")
                    time.sleep(RETRY_DELAY_SEC)
                    continue  # Повторяем запрос с тем же ключом

                if response.status_code == 200:
                    data = response.json()
                    return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                elif response.status_code == 503:
                    retries += 1
                    print(
                        f"[WARNING] Модель перегружена (503). Попытка повторить запрос через {RETRY_DELAY_SEC} секунд... (Попытка {retries} из {MAX_503_RETRIES})")
                    time.sleep(RETRY_DELAY_SEC)
                    continue  # Повторяем запрос с тем же ключом
                elif response.status_code == 429:
                    print(f"[WARNING] Ключ {self.current_key} исчерпан. Переключаемся.")
                    self.switch_to_next_key()
                    break  # Переходим к следующему ключу
                elif response.status_code == 400 and "API_KEY_INVALID" in response.text:
                    print(f"[ERROR] Неверный ключ: {self.current_key}. Пропускаем его.")
                    self.switch_to_next_key()
                    break  # Переходим к следующему ключу
                else:
                    print(f"[ERROR] Ошибка API {response.status_code}: {response.text}. Переключаемся на запасную LLM.")
                    return self._generate_fallback(system_prompt, user_prompt, temperature, max_output_tokens)
            else:
                # Повторы 503 для текущего ключа исчерпаны — пробуем следующий ключ
                print(f"[WARNING] Ключ {self.current_key}: исчерпаны повторы 503. Переходим к следующему ключу.")
                self.switch_to_next_key()
                continue  # Переходим к следующему ключу

        # Если все ключи исчерпаны / Gemini недоступен — переключаемся на запасную LLM
        print("[WARNING] Gemini недоступен. Переключаемся на запасную LLM.")
        return self._generate_fallback(system_prompt, user_prompt, temperature, max_output_tokens)

    def _generate_fallback(self, system_prompt: str, user_prompt: str, temperature: float,
                           max_output_tokens: int) -> str:
        """Запасная генерация через локальную/облачную OpenAI-совместимую LLM (без SOCKS5-прокси)."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            print(f"[INFO] Запрос к запасной LLM: {FALLBACK_LLM_URL} (модель {FALLBACK_LLM_MODEL})")
            # Отдельный клиент БЕЗ прокси — эндпоинт в локальной сети.
            # Таймаут 600с: модель с рассуждением (thinking) на крупных промптах считает долго.
            with httpx.Client(timeout=httpx.Timeout(600)) as client:
                resp = client.post(
                    f"{FALLBACK_LLM_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {FALLBACK_LLM_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": FALLBACK_LLM_MODEL, "messages": messages,
                          "temperature": temperature, "max_tokens": max_output_tokens,
                          "stream": False},
                )
                resp.raise_for_status()
                data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[ERROR] Запасная LLM тоже недоступна: {e}")
            return ""
