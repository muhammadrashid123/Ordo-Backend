import logging

from apps.accounts.serializers import UserSerializer

logger = logging.getLogger(__name__)


def jwt_response_payload_handler(token, user=None, request=None):
    return {"token": token, "profile": UserSerializer(user, context={"exclude_vendors": True}).data}
