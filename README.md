### README для GitHub

---

# UtrIskra

**UtrIskra** — это проект для автоматической генерации вдохновляющих изображений и их публикации в Telegram. Проект включает в себя Telegram-бота, автоматизированный планировщик задач и интеграцию с API Stability AI и Gemini Pro.

---

## Основные возможности

- **Генерация изображений**: Создание уникальных вдохновляющих изображений на основе текстовых подсказок.
- **Публикация в Telegram**:
  - Автоматическая публикация изображений в чатах/каналах.
  - Возможность публикации через Telegram Stories (с использованием Telethon).
- **Планировщик задач**: Ежедневная публикация изображений в 9:00.
- **Гибкость**:
  - Интеграция с Stability AI для генерации изображений.
  - Использование Gemini Pro для создания текстовых подсказок.

---

## Структура проекта

```
UtrIskra/
├── bot/
│   ├── create_telegram_session.py  # Скрипт для создания сессии Telethon
│   ├── daily_runner.py            # Скрипт для автоматической публикации
│   ├── scheduler.py               # Планировщик задач
│   ├── story_sender.py            # Отправка сторис через Telethon
│   ├── telegram_bot.py            # Telegram-бот на основе aiogram
├── services/
│   ├── gemini_service.py          # Интеграция с Gemini Pro API
│   ├── stability_service.py       # Интеграция с Stability AI
├── utils/
│   ├── database.py                # Управление базой данных
│   ├── logger.py                  # Логирование
├── storage/
│   ├── images/                    # Сохранение сгенерированных изображений
│   ├── database/                  # База данных SQLite
├── config.py                      # Конфигурация проекта
├── requirements.txt               # Список зависимостей
├── README.md                      # Документация проекта
```

---

## Установка и настройка

### 1. Клонирование репозитория

```bash
git clone https://github.com/your-username/UtrIskra.git
cd UtrIskra
```

### 2. Создание виртуального окружения

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
.\.venv\Scripts\activate   # Windows
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения

Создайте файл `.env` в корне проекта со следующим содержимым:

```
STABILITY_API_KEY=your_stability_api_key
GEMINI_API_KEY=your_gemini_api_key
TELEGRAM_TOKEN=your_telegram_bot_token
TARGET_CHAT_ID=your_target_chat_id
TELETHON_API_ID=your_telethon_api_id
TELETHON_API_HASH=your_telethon_api_hash
TELETHON_PEER=your_telethon_peer
PROXY_URL=your_socks5_proxy_url
GEMINI_API_KEYS=your_additional_gemini_api_keys
```

### 5. Инициализация базы данных

```bash
python utils/database.py
```

### 6. Создание сессии Telethon

```bash
python bot/create_telegram_session.py
```

---

## Использование

### 1. Автоматическая публикация

Запуск ежедневной публикации изображений через `cron`:

```bash
python bot/daily_runner.py
```

### 2. Telegram-бот

Запуск Telegram-бота:

```bash
python bot/telegram_bot.py
```

### 3. Публикация сторис

Отправка изображений в Telegram Stories:

```bash
python bot/story_sender.py
```

---

## Интеграция с API

### Gemini Pro
Используется для создания креативных текстовых подсказок. 

### Stability AI
Используется для генерации изображений на основе текстовых подсказок.

---

## Планировщик задач

Для запуска ежедневной публикации в 9:00 настройте `cron`:
```bash
0 9 * * * /path/to/venv/bin/python /path/to/UtrIskra/bot/daily_runner.py >> /path/to/logs/daily_runner.log 2>&1
```

---

## Лицензия

Этот проект лицензирован под MIT License.

---

Если есть вопросы, пишите! 😊
