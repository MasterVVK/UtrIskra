---

# UtrIskra

**UtrIskra** - проект для автоматической генерации и публикации визуальных историй с использованием различных AI-генераторов, таких как Stability AI, Flux, Yandex-Art, MidJourney, и других. Проект включает функционал для интеграции с Telegram и автоматической отправки результатов.

---

## Основные возможности

- **Генерация изображений:**
  - Работа с популярными AI-сервисами: Stability AI, Flux, Yandex-Art, MidJourney.
  - Генерация промптов через Gemini Pro.
  - Возможность персонализации промптов и настройки параметров генерации.

- **Публикация в Telegram:**
  - Автоматическая отправка изображений в Telegram-чат.
  - Использование Telethon и Aiogram для взаимодействия с Telegram API.

- **Работа с базой данных:**
  - Сохранение метаданных о сгенерированных изображениях.
  - Организация файлового хранения результатов генерации.

---

## Структура проекта

**Основные файлы:**
- `main.py`: Запуск планировщика задач для автоматической публикации историй.
- `config.py`: Конфигурационный файл с настройками и API-ключами.

**Модули:**
1. **Утилиты (`utils`):**
   - `database.py`: Управление базой данных SQLite.
   - `logger.py`: Настройка логирования.

2. **Сервисы (`services`):**
   - `gemini_service.py`: Взаимодействие с Gemini Pro для генерации текстовых промптов.
   - `stability_service.py`: Использование Stability AI для генерации изображений.
   - `flux_service.py`: Взаимодействие с Flux API для генерации изображений.
   - `midjourney_service.py`: Поддержка MidJourney API.
   - `yandex_service.py`: Работа с Yandex-Art для художественной генерации.

3. **Бот (`bot`):**
   - `telegram_bot.py`: Telegram-бот для управления генерацией и публикацией.
   - `scheduler.py`: Планировщик задач для автоматической публикации историй.
   - `story_sender.py`: Отправка историй через Telegram.
   - `create_telegram_session.py`: Скрипт для настройки сессии Telethon.

4. **Раннеры:**
   - `daily_runner.py`: Генерация изображений через Stability AI.
   - `flux_runner.py`: Использование Flux для создания историй.
   - `yandex_runner.py`: Интеграция с Yandex-Art.
   - `midjourney_runner.py`: Генерация через MidJourney.

---

## Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/MasterVVK/UtrIskra.git
   cd UtrIskra
   ```

2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Создайте файл `.env` и добавьте API-ключи:
   ```env
   STABILITY_API_KEY=ваш_ключ
   GEMINI_API_KEY=ваш_ключ
   TELEGRAM_TOKEN=ваш_токен
   TARGET_CHAT_ID=ваш_chat_id
   BFL_API_KEY=ваш_flux_ключ
   FOLDER_ID=ваш_folder_id
   OAUTH_TOKEN=ваш_yandex_oauth_token
   BASE_STORAGE_PATH=storage
   FONTS_PATH=fonts
   ```

4. Настройте базу данных:
   ```bash
   python utils/database.py
   ```

---

## Использование

### Запуск планировщика задач
Для автоматической публикации историй:
```bash
python main.py
```

### Запуск Telegram-бота
```bash
python bot/telegram_bot.py
```

### Запуск раннеров
- Stability AI: `python daily_runner.py`
- Flux: `python flux_runner.py`
- Yandex: `python yandex_runner.py`
- MidJourney: `python midjourney_runner.py`

---

## Дополнительная информация

**Файлы базы данных (`daily_images.db`):**
- `id`: Уникальный идентификатор.
- `date`: Дата создания изображения.
- `system_prompt`: Системный промпт.
- `user_prompt`: Промпт пользователя.
- `generated_prompt`: Итоговый промпт.
- `image_path`: Путь к изображению.

---
