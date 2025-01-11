import os
import datetime
import logging

logger = logging.getLogger(__name__)

def generate_dynamic_prompt(prompts_file: str) -> tuple:
    """
    Читает системный и пользовательский промпт из указанного файла.
    :param prompts_file: Путь к файлу с промптами.
    :return: Кортеж (system_prompt, user_prompt).
    """
    try:
        with open(prompts_file, "r", encoding="utf-8") as file:
            lines = file.readlines()

        system_prompt = None
        user_prompt = None

        for line in lines:
            if line.startswith("SYSTEM_PROMPT:"):
                system_prompt = line.replace("SYSTEM_PROMPT:", "").strip()
            elif line.startswith("USER_PROMPT:"):
                user_prompt = line.replace("USER_PROMPT:", "").strip()

        if not system_prompt or not user_prompt:
            raise ValueError(f"Файл {prompts_file} должен содержать 'SYSTEM_PROMPT' и 'USER_PROMPT'.")

        # Заменяем {current_date} на текущую дату в пользовательском промпте
        current_date = datetime.datetime.now().strftime("%d %B %Y")
        user_prompt = user_prompt.replace("{current_date}", current_date)

        return system_prompt, user_prompt
    except FileNotFoundError:
        logger.error(f"Файл {prompts_file} не найден. Проверьте путь.")
        raise
    except Exception as e:
        logger.error(f"Ошибка при чтении промптов из файла {prompts_file}: {e}")
        raise
