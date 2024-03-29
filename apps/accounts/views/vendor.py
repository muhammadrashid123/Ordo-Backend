import logging

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts import models as m
from apps.accounts import serializers as s

logger = logging.getLogger(__name__)


class VendorViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = s.VendorSerializer
    queryset = m.Vendor.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["enabled"]

    def update(self, request, *args, **kwargs):
        kwargs.setdefault("partial", True)
        return super().update(request, *args, **kwargs)

    @action(detail=False, methods=["post"], url_path="shipping_methods")
    def shipping_methods(self, request, *args, **kwargs):
        # TODO: currently hard code because not sure about shipping method across all vendors
        vendors = request.data.get("vendors")
        ret = {
            "henry_schein": [
                "UPS Standard Delivery",
                "Next Day Delivery (extra charge)",
                "Saturday Delivery (extra charge)",
                "Next Day 10:30 (extra charge)",
                "2nd Day Air (extra charge)",
            ]
        }
        ret = {k: v for k, v in ret.items() if k in vendors}
        return Response(ret)
