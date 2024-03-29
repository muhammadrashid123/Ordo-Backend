from . import models
from rest_framework import serializers


class BadImageUrlSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.BadImageUrl
        fields = ["id", "image_url", "created_at"]
        read_only_fields = ["created_at", "id"]

