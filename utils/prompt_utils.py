import os
import datetime
import logging

logger = logging.getLogger(__name__)  # Устанавливаем логгер для текущего модуля

def generate_dynamic_prompt(prompts_file: str) -> tuple:
    """
    Читает системный и пользовательский промпт из файла с многострочным форматом.
    :param prompts_file: Путь к файлу с промптами.
    :return: Кортеж (system_prompt, user_prompt).
    """
    try:
        with open(prompts_file, "r", encoding="utf-8") as file:
            content = file.read()

        # Извлекаем SYSTEM_PROMPT
        system_prompt_start = "---SYSTEM_PROMPT---"
        system_prompt_end = "---END_SYSTEM_PROMPT---"
        system_prompt = content.split(system_prompt_start)[1].split(system_prompt_end)[0].strip()

        # Извлекаем USER_PROMPT
        user_prompt_start = "---USER_PROMPT---"
        user_prompt_end = "---END_USER_PROMPT---"
        user_prompt = content.split(user_prompt_start)[1].split(user_prompt_end)[0].strip()

        # Заменяем {current_date} в пользовательском промпте
        current_date = datetime.datetime.now().strftime("%d %B %Y")
        user_prompt = user_prompt.replace("{current_date}", current_date)

        logger.info("Промпты успешно извлечены из файла.")
        return system_prompt, user_prompt
    except FileNotFoundError:
        logger.error(f"Файл {prompts_file} не найден. Проверьте путь.")
        raise
    except Exception as e:
        logger.error(f"Ошибка при чтении промптов из файла {prompts_file}: {e}")
        raise
