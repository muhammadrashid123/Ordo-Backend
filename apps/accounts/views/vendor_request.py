import logging

from rest_framework.viewsets import ModelViewSet

from apps.accounts import models as m
from apps.accounts import serializers as s

logger = logging.getLogger(__name__)


class VendorRequestViewSet(ModelViewSet):
    queryset = m.VendorRequest.objects.all()
    serializer_class = s.VendorRequestSerializer

    def get_queryset(self):
        return self.queryset.filter(company_id=self.kwargs["company_pk"])
