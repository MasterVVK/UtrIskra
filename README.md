
---

# UtrIskra

**UtrIskra** - это проект для автоматической генерации и публикации визуальных историй с использованием различных AI-генераторов, таких как Gemini Pro, Stability AI, Flux и другие. Проект интегрируется с Telegram для автоматической отправки результатов в указанный чат.

---

## Основные возможности

- **Генерация изображений**:
  - Использование AI-сервисов (Stability AI, Flux, Yandex, MidJourney).
  - Создание уникальных промптов через Gemini Pro.
- **Публикация в Telegram**:
  - Автоматическая публикация изображений с датой и подписью.
  - Возможность настройки публикаций через команды Telegram-бота.
- **Работа с базой данных**:
  - Хранение данных о созданных изображениях (промпты, дата, путь к файлу).

---

## Структура проекта

**Основные файлы:**
- `main.py` - Запуск планировщика задач для публикаций.
- `config.py` - Конфигурация проекта с API-ключами и путями.
- `stability_test.py` - Тестовый скрипт для Stability AI.

**Модули:**
1. **Утилиты (`utils`)**:
   - `database.py` - Управление базой данных для сохранения информации о созданных изображениях.
   - `logger.py` - Настройка и управление логированием.

2. **Сервисы (`services`)**:
   - `gemini_service.py` - Генерация промптов через Gemini Pro.
   - `stability_service.py` - Генерация изображений через Stability AI.
   - `flux_service.py` - Работа с API Flux.
   - `midjourney_service.py` - Взаимодействие с MidJourney API.
   - `yandex_service.py` - Использование Yandex-Art для генерации изображений.

3. **Бот (`bot`)**:
   - `telegram_bot.py` - Telegram-бот с командами для генерации и публикации изображений.
   - `scheduler.py` - Планировщик задач для регулярной отправки историй.
   - `story_sender.py` - Отправка визуальных историй в Telegram.
   - `create_telegram_session.py` - Скрипт для создания сессии Telethon.

4. **Раннеры**:
   - `daily_runner.py` - Генерация изображений и публикация с использованием Stability AI.
   - `flux_runner.py` - Генерация изображений с использованием Flux (аналогично `daily_runner.py`).
   - `midjourney_runner.py` - Работа с MidJourney для генерации историй.
   - `yandex_runner.py` - Использование Yandex для создания художественных изображений.

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

3. Создайте файл `.env` в корневой папке и добавьте ключи:
   ```env
   STABILITY_API_KEY=ваш_ключ
   GEMINI_API_KEY=ваш_ключ
   TELEGRAM_TOKEN=ваш_ключ
   TARGET_CHAT_ID=ваш_чат_id
   BFL_API_KEY=ваш_flux_ключ
   BASE_STORAGE_PATH=storage
   FONTS_PATH=fonts
   ```

4. Настройте базу данных:
   ```bash
   python -m utils.database
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

### Тестовые скрипты
- Stability AI: `python stability_test.py`
- Flux: `python flux_runner.py`
- Yandex: `python yandex_runner.py`

---

## Структура данных

- База данных (`daily_images.db`):
  - `id` - уникальный идентификатор.
  - `date` - дата создания изображения.
  - `system_prompt` - системный промпт.
  - `user_prompt` - пользовательский промпт.
  - `generated_prompt` - итоговый промпт.
  - `image_path` - путь к изображению.

---

