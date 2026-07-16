"""Общие singleton-объекты веб-приложения."""
from webapp.scheduler_service import SchedulerService
from webapp.task_manager import TaskManager

task_manager = TaskManager()
scheduler_service = SchedulerService(task_manager)
