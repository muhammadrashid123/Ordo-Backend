import datetime

import jwt
from django.conf import settings
from django.utils import timezone


def ensure_jwt_payload_correct(token, user):
    payload = jwt.decode(token, key=settings.SECRET_KEY, algorithms=["HS256"])
    assert payload["user_id"] == user.pk
    assert payload["username"] == user.email
    assert payload["email"] == user.email
    exp = datetime.datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert (timezone.localtime() + settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] - exp).total_seconds() < 2
