import logging
import logging.handlers
import os

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger
from celery._state import get_current_task

from ecs_logging import StdlibFormatter


class StdLibTaskFormatter(StdlibFormatter):
    def format(self, record):
        task = get_current_task()
        if task and task.request:
            record.__dict__.update(task_id=task.request.id,
                                   task_name=task.name)
        else:
            record.__dict__.setdefault('task_name', None)
            record.__dict__.setdefault('task_id', 0)
        return super().format(record)


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("FORKED_BY_MULTIPROCESSING", "1")


@after_setup_logger.connect
def config_loggers(logger, *args, **kwargs):
    formatter = StdLibTaskFormatter()
    for handler in logger.handlers:
        handler.setFormatter(formatter)


@after_setup_task_logger.connect
def setup_task_logger(logger, *args, **kwargs):
    logger.setLevel("DEBUG")
    formatter = StdLibTaskFormatter()
    for handler in logger.handlers:
        handler.setFormatter(formatter)


app = Celery("ordo-back")
app.config_from_object("config.celeryconfig")
app.autodiscover_tasks()
