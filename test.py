import requests
from PIL import Image

api_key="sk-PmcOQ3J5dphmzSWkPQYbtTKKN6FWbpVMPlqXWiNakNYN8MUp"

# Запрос к API для генерации изображения
response = requests.post(
    f"https://api.stability.ai/v2beta/stable-image/generate/sd3",
    headers={
        "authorization": f"Bearer {api_key}",
        "accept": "image/*"
    },
    files={"none": ''},
    data={
        "prompt": "red cat with blue eyes wearing a pink heart shaped glasses without lenses ultrahd",
        "aspect_ratio": "9:16",
        "output_format": "jpeg",
    },
)
# Проверка успешного ответа
if response.status_code == 200:
    # Сохранение сгенерированного изображения
    with open("./story.jpg", 'wb') as file:
        file.write(response.content)
    # Открытие изображения с помощью Pillow
    with Image.open("./story.jpg") as img:
        # Получение текущих размеров изображения
        width, height = img.size
        # Целевое соотношение 9:16
        target_aspect_ratio = 9 / 16
        current_aspect_ratio = width / height
        if current_aspect_ratio > target_aspect_ratio:
            # Ширина изображения слишком большая, нужно обрезать по ширине
            new_width = int(height * target_aspect_ratio)
            left = (width - new_width) // 2
            right = left + new_width
            cropped_img = img.crop((left, 0, right, height))
        elif current_aspect_ratio < target_aspect_ratio:
            # Высота изображения слишком большая, нужно обрезать по высоте
            new_height = int(width / target_aspect_ratio)
            top = (height - new_height) // 2
            bottom = top + new_height
            cropped_img = img.crop((0, top, width, bottom))
        else:
            # Изображение уже в нужных пропорциях
            cropped_img = img
        # Сохранение обрезанного изображения
        cropped_img.save("./story_cropped.jpg")
        print("Изображение успешно обрезано и сохранено как story_cropped.jpg")
else:
    raise Exception(str(response.json()))