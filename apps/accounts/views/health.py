import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthCheck(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(status=HTTP_200_OK)
