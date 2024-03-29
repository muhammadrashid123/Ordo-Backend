from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from . import models as m
from . import serializers as s
from .services import NotificationService

# Create your views here.


class NotificationModelViewset(ModelViewSet):
    serializer_class = s.NotificationRecipientSerializer
    queryset = m.NotificationRecipient.objects.all()
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "post"]

    def get_queryset(self):
        queryset = self.queryset.filter(is_read=False, user=self.request.user)
        if self.action == "list":
            queryset = queryset.select_related("notification")
        return queryset

    @action(detail=False, methods=["post"], url_path="read")
    def mark_as_read(self, request, *args, **kwargs):
        serializer = s.NotificationReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        queryset = None if serializer.validated_data["mark_all"] else serializer.validated_data["notifications"]
        NotificationService.mark_all_as_read(user=request.user, queryset=queryset)
        return Response({"message": "Successfully updated"})
