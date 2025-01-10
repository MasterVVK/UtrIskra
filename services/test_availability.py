import requests
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Ваши ключи
KANDINSKY_API_KEY = ""
KANDINSKY_SECRET_KEY = ""

BASE_URL = "https://api-key.fusionbrain.ai/"
AUTH_HEADERS = {
    "X-Key": f"Key {KANDINSKY_API_KEY}",
    "X-Secret": f"Secret {KANDINSKY_SECRET_KEY}"
}

def get_model_id():
    """Получает модель ID из API."""
    url = f"{BASE_URL}key/api/v1/models"
    try:
        logger.info("Получаем ID модели...")
        response = requests.get(url, headers=AUTH_HEADERS, timeout=30)
        response.raise_for_status()
        models = response.json()
        model_id = models[0]["id"]
        logger.info(f"Получен model_id: {model_id}")
        return model_id
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при получении model_id: {e}")
        raise

def check_availability(model_id):
    """Проверяет доступность API Kandinsky."""
    url = f"{BASE_URL}key/api/v1/text2image/availability"
    try:
        logger.info("Отправляем запрос на проверку доступности сервиса Kandinsky...")
        response = requests.get(
            url,
            headers=AUTH_HEADERS,
            params={"model_id": model_id},  # Передаем model_id как параметр URL
            timeout=30
        )
        response.raise_for_status()  # Проверяем успешность запроса

        # Логируем код ответа и текст
        logger.info(f"Статус-код ответа: {response.status_code}")
        logger.info(f"Текст ответа: {response.text}")

        # Пытаемся извлечь JSON
        try:
            response_data = response.json()
            logger.info(f"JSON ответа: {response_data}")
        except ValueError:
            logger.warning("Ответ не является JSON.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке запроса: {e}")

if __name__ == "__main__":
    try:
        model_id = get_model_id()
        check_availability(model_id)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
