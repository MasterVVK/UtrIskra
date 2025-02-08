import time
import httpx
from httpx_socks import SyncProxyTransport
from config import GEMINI_API_KEYS, PROXY_URL
import sys  # Для завершения программы


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
            while retries < 3:
                try:
                    response = self.client.post(
                        #"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest:generateContent",
                        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-pro-exp-02-05:generateContent",
                        # "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent",
                        params={"key": self.current_key},
                        headers={"Content-Type": "application/json"},
                        json={
                            "generationConfig": generation_config,
                            "contents": [{"parts": [{"text": system_prompt}, {"text": user_prompt}]}],
                        },
                    )
                except Exception as e:
                    print(f"[ERROR] Ошибка при запросе: {e}")
                    self.switch_to_next_key()
                    break  # Переходим к следующему ключу

                if response.status_code == 200:
                    data = response.json()
                    return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                elif response.status_code == 503:
                    retries += 1
                    print(
                        f"[WARNING] Модель перегружена (503). Попытка повторить запрос через 5 секунд... (Попытка {retries} из 5)")
                    time.sleep(50)
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
                    print(f"[ERROR] Ошибка API {response.status_code}: {response.text}")
                    return ""
            else:
                # Если 3 попытки с кодом 503 исчерпаны, завершаем работу программы
                print("[CRITICAL] Превышено число попыток получения ответа с кодом 503. Завершение работы.")
                sys.exit(1)

        # Если все ключи исчерпаны
        print("[CRITICAL] Все API-ключи недействительны или исчерпаны. Завершение работы.")
        sys.exit(1)
