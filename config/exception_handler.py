import sentry_sdk
from django.conf import settings
from django.db import IntegrityError
from rest_framework import status
from rest_framework.views import Response, exception_handler


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first to get the standard error response.
    response = exception_handler(exc, context)

    # if there is an IntegrityError and the error response hasn't already been generated
    if isinstance(exc, IntegrityError) and not response:
        msg = (
            "It seems there is a conflict between the data you are trying to save and your current "
            "data. Please review your entries and try again."
        )
        if settings.DEBUG:
            msg = f"{msg}: {exc}"
        response = Response(
            {"message": msg},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sentry_sdk.capture_exception(exc)
    return response
