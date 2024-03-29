from rest_framework import serializers

from . import models as m


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.Notification
        fields = (
            "metadata",
            "event",
        )


class NotificationRecipientSerializer(serializers.ModelSerializer):
    notification = NotificationSerializer()

    class Meta:
        model = m.NotificationRecipient
        fields = ("id", "notification", "created_at", "updated_at", "is_read")


class NotificationReadSerializer(serializers.Serializer):
    notifications = serializers.PrimaryKeyRelatedField(
        queryset=m.NotificationRecipient.objects.all(), many=True, required=False
    )
    mark_all = serializers.BooleanField(default=False)
