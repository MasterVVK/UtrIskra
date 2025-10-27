# Image Operations

Операции для работы с изображениями: загрузка, управление и обработка.

## 📤 Image Upload - Загрузка изображений

Загрузка изображений для использования в Midjourney операциях.

**Endpoint:** `POST /v1/midjourney/image/upload`

### Параметры запроса
```json
{
  "image": "base64_string (обязательно)",
  "extension": "png|jpg|jpeg|webp (обязательно)",
  "expiration": 1296000000 (опционально, по умолчанию: 15 дней в мс)"
}
```

### Успешный ответ
```json
{
  "requestId": "uuid",
  "url": "https://cdn.kolersky.com/uuid/image.png",
  "expiration": 1296000000,
  "code": 200
}
```

### Поддерживаемые форматы
- **PNG**: Для прозрачности.
- **JPG/JPEG**: Для фотографий.
- **WebP**: Для оптимизации размера.

### Ограничения
- Максимальный размер файла: 100MB.
- Автоматическое удаление через 15 дней.
- Base64 кодировка обязательна.

### Примеры использования
#### Загрузка PNG изображения
```bash
curl -X POST "https://api.kolersky.com/v1/midjourney/image/upload" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
    "extension": "png",
    "expiration": 3600000
  }'
```

### Обработка ошибок
```json
{
  "err": "Missing required fields",
  "code": 400,
  "message": "image (base64) and extension are required"
}
```

```json
{
  "err": "Invalid image data",
  "code": 400,
  "message": "Failed to decode base64 image data"
}
```

### Особенности
- **Бесплатная операция**: Не расходует requests.
- **CDN хранение**: Изображения доступны по URL.
- **Автоматическая очистка**: Удаление через 15 дней.
- **Безопасность**: Логирование загрузок с IP.

## 🔍 Image Analysis
Для анализа и описания изображений используйте `/v1/midjourney/generate` с `taskType: text-to-image` и параметром `fileUrl` или `fileUrls`.

## 📊 Управление хранилищем
- **Временное хранение**: Изображения хранятся в `/temp/{requestId}/{filename}`.
- **CDN URLs**: `https://cdn.kolersky.com/temp/uuid/image.png`.
- **Мониторинг**: Статистика через `/v1/usage`.

## 🛠️ Интеграция с Midjourney
1. Загрузите изображение через `/v1/midjourney/image/upload`.
2. Получите CDN URL.
3. Используйте URL в операциях:
   - **Describe**: Анализ через `/v1/midjourney/generate` (`taskType: text-to-image`, `fileUrl`).
   - **Blend**: Смешивание через `/v1/midjourney/generate` (`taskType: image-to-image`, `fileUrls`).
   - **Video**: Генерация видео через `/v1/midjourney/generate` (`taskType: image-to-video`, `fileUrl`).

### Пример полной интеграции
```bash
# 1. Загрузка изображения
UPLOAD_RESPONSE=$(curl -X POST "https://api.kolersky.com/v1/midjourney/image/upload" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"image": "base64_data", "extension": "png"}')

IMAGE_URL=$(echo $UPLOAD_RESPONSE | jq -r '.url')

# 2. Анализ изображения
curl -X POST "https://api.kolersky.com/v1/midjourney/generate" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d "{\"taskType\": \"text-to-image\", \"fileUrl\": \"$IMAGE_URL\", \"speed\": \"fast\"}"

# 3. Создание видео
curl -X POST "https://api.kolersky.com/v1/midjourney/generate" \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d "{\"taskType\": \"image-to-video\", \"fileUrl\": \"$IMAGE_URL\", \"prompt\": \"gentle movement\", \"motion\": \"low\"}"
```

## ⚙️ Конфигурация
### Переменные окружения
```env
MAX_FILE_SIZE=104857600
TEMP_DIR=temp
CDN_BASE_URL=https://cdn.kolersky.com
CDN_TEMP_URL=/temp
DEFAULT_EXPIRATION=1296000000
```

## 🔒 Безопасность
- Валидация base64.
- Проверка типов файлов.
- Ограничение размера файлов.
- Логирование операций.
- Автоматическая очистка.

## 📈 Мониторинг и аналитика
- **Метрики**: Количество файлов, типы, размеры, время хранения.
- **Хранилище**: Мониторинг объема данных и дискового пространства.