# Video Operations

Операции для обработки, редактирования и генерации видео контента.

## 🎬 Video Generation

Создание видео из статичных изображений с добавлением движения. Используется эндпоинт `/v1/midjourney/generate`.

**Endpoint:** `POST /v1/midjourney/generate`

### Параметры запроса
```json
{
  "taskType": "image-to-video|image-to-video-hd (обязательно)",
  "prompt": "string (обязательно)",
  "fileUrl": "string (обязательно, если не используется fileUrls)",
  "fileUrls": ["string"] (обязательно, если не используется fileUrl, 1 URL)",
  "motion": "low|high (обязательно, по умолчанию: high)",
  "videoBatchSize": "1|2|4 (опционально, по умолчанию: 1)",
  "aspectRatio": "1:2|9:16|2:3|3:4|5:6|6:5|4:3|3:2|1:1|16:9|2:1 (опционально, по умолчанию: 1:1)",
  "version": "7|6.1|6|5.2|5.1|niji6 (опционально, по умолчанию: 7)",
  "waterMark": "string (опционально)",
  "callBackUrl": "string<uri> (опционально)"
}
```

### Примечания
- Используйте либо `fileUrl`, либо `fileUrls`, но не оба одновременно.
- Для `image-to-video` и `image-to-video-hd` `fileUrls` принимает только один URL.

### Пример использования
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/generate" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "taskType": "image-to-video",
    "fileUrl": "https://cdn.kolersky.com/image.jpg",
    "prompt": "gentle waves moving in the lake, soft breeze",
    "motion": "low",
    "videoBatchSize": 1,
    "aspectRatio": "16:9",
    "version": "7",
    "waterMark": "my_watermark",
    "callBackUrl": "https://api.kolersky.com/callback"
  }'
```

### Особенности
- **Стоимость**: 15 requests.
- **Время обработки**: 2-5 минут.
- **Качество**: Зависит от качества исходного изображения.
- **Хранение**: Видео хранятся 15 дней.

---

## 🎥 Video Editing - Редактирование видео

Комплексное редактирование видео с управлением звуком, субтитрами и аудио-дорожками.

**Endpoint:** `POST /v1/midjourney/edit`

### Параметры запроса
```json
{
  "requestId": "string (опционально)",
  "video": "base64_string (опционально)",
  "url": "string (опционально)",
  "volumeAdjustments": {
    "startTime": "number (секунды)",
    "endTime": "number (секунды)",
    "volume": "number (0.0-2.0)"
  },
  "subtitleOptions": {
    "font": "string (опционально)",
    "color": "string (hex, опционально)",
    "size": "number (опционально)",
    "position": "string (опционально)"
  },
  "stemAdjustments": {
    "vocals": "number (-20 to +20 dB)",
    "drums": "number (-20 to +20 dB)",
    "bass": "number (-20 to +20 dB)",
    "guitar": "number (-20 to +20 dB)",
    "piano": "number (-20 to +20 dB)"
  }
}
```

### Источники видео
Укажите один из источников:
1. **requestId** - ID предыдущего запроса.
2. **video** - base64 закодированное видео.
3. **url** - URL видео файла.

### Настройки редактирования
#### Volume Adjustments (Громкость)
```json
{
  "volumeAdjustments": {
    "startTime": 10,
    "endTime": 30,
    "volume": 0.5
  }
}
```
- Управление громкостью в указанном временном интервале.
- `volume`: 0.0 (без звука) - 2.0 (удвоенная громкость).

#### Subtitle Options (Субтитры)
```json
{
  "subtitleOptions": {
    "font": "Arial",
    "color": "#FFFFFF",
    "size": 24,
    "position": "bottom"
  }
}
```
- Автоматическое распознавание речи и генерация субтитров.
- Настройка внешнего вида текста.

#### Stem Adjustments (Аудио-дорожки)
```json
{
  "stemAdjustments": {
    "vocals": 5,
    "drums": -3,
    "bass": 2,
    "guitar": 0,
    "piano": -10
  }
}
```
- Разделение аудио на компоненты с помощью ИИ.
- Независимая настройка каждой дорожки.

### Примеры использования
#### Простое редактирование громкости
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/edit" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://cdn.kolersky.com/video.mp4",
    "volumeAdjustments": {
      "startTime": 0,
      "endTime": 10,
      "volume": 0.3
    }
  }'
```

#### Полное редактирование с субтитрами
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/edit" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "requestId": "previous-request-uuid",
    "subtitleOptions": {
      "font": "Roboto",
      "color": "#FFFFFF",
      "size": 28,
      "position": "bottom"
    },
    "stemAdjustments": {
      "vocals": 3,
      "drums": -5
    }
  }'
```

### Ответы
#### Принятие в обработку
```json
{
  "requestId": "uuid",
  "status": "accepted",
  "code": 200
}
```

#### Успешное завершение
```json
{
  "requestId": "uuid",
  "status": "success",
  "code": 200,
  "output": {
    "video": "https://cdn.kolersky.com/uuid/edited_video.mp4",
    "metadata": {
      "originalRequestId": null,
      "editsApplied": ["volume", "subtitles", "stems"],
      "creditsUsed": 1
    }
  }
}
```

### Стоимость и лимиты
- **Стоимость**: 1 request за операцию.
- **Время обработки**: 1-10 минут.
- **Максимальный размер**: Ограничен конфигурацией сервера.

---

## 📊 Сравнение операций

| Операция | Источник | Стоимость | Время | Особенности |
|----------|----------|-----------|-------|-------------|
| Video Generation | Изображение | 15 requests | 2-5 мин | Добавление движения |
| Video Editing | Видео файл | 1 request | 1-10 мин | Редактирование существующего |

## 🔄 Workflow редактирования видео
1. **Подготовка источника**:
   - Загрузка видео через URL/base64 или использование ID предыдущего запроса.
2. **Настройка параметров**:
   - Громкость, субтитры, аудио-дорожки.
   - Комбинирование нескольких типов редактирования.
3. **Асинхронная обработка**:
   - Получение `requestId`.
   - Мониторинг статуса через `/v1/status`.
4. **Получение результата**:
   - CDN ссылка на обработанное видео.
   - Метаданные о примененных изменениях.

## ⚠️ Ограничения и рекомендации
### Технические ограничения
- Максимальная длина видео: Зависит от конфигурации.
- Поддерживаемые форматы: MP4, MOV, AVI.
- Максимальный размер файла: Настраивается в конфигурации.

### Рекомендации по качеству
- Используйте видео хорошего качества.
- Для субтитров обеспечивайте четкую речь.
- Тестируйте настройки на коротких фрагментах.

### Оптимизация
- Разделяйте сложные редактирования на этапы.
- Используйте предварительный анализ для настроек.
- Мониторьте использование requests.

## 🔧 Расширенные возможности
### Batch Processing
Несколько видео обрабатываются параллельно через отдельные запросы.

### Chain Operations
Результат одного редактирования используется как источник для следующего:
```json
{
  "requestId": "first-edit-request-id",
  "volumeAdjustments": { "volume": 0.8 }
}
```

### Интеграция с Midjourney
1. Создайте изображение через `/v1/midjourney/generate` с `taskType: text-to-image`.
2. Сгенерируйте видео через `/v1/midjourney/generate` с `taskType: image-to-video`.
3. Отредактируйте видео через `/v1/midjourney/edit`.

## 📈 Мониторинг и аналитика
### Метрики обработки
- Время обработки различных типов редактирования.
- Успешность операций.
- Распределение по типам редактирования.

### Использование ресурсов
- Потребление requests по пользователям.
- Нагрузка на систему обработки видео.
- Эффективность алгоритмов.