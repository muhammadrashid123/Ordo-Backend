from ..utils import get_bool_config
from .base import *  # noqa
from .base import REST_FRAMEWORK

DEBUG = True

# Email settings
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = "/tmp/app-messages"
# CELERY_TASK_ALWAYS_EAGER = True
CORS_ALLOW_ALL_ORIGINS = True

ENABLE_PSEUDO_EMAIL_AUTH = get_bool_config("ENABLE_PSEUDO_EMAIL_AUTH", default=False)

DEFAULT_AUTHENTICATION_CLASSES = REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]

if ENABLE_PSEUDO_EMAIL_AUTH:
    DEFAULT_AUTHENTICATION_CLASSES = (
        *DEFAULT_AUTHENTICATION_CLASSES,
        "services.utils.pseudo_email_authentication.PseudoEmailAuthentication",
    )

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": DEFAULT_AUTHENTICATION_CLASSES,
}

ALLOWED_HOSTS = ["*"]

SPECTACULAR_SETTINGS = {
    "TITLE": "Ordo API",
    "DESCRIPTION": "Ordo API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # OTHER SETTINGS
}
