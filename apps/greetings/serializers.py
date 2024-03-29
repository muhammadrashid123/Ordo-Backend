from rest_framework import serializers

from .models import Greetings


class GreetingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Greetings
        fields = "__all__"
