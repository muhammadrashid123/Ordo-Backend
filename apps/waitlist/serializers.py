# serializers.py
from rest_framework import serializers

from .models import WaitList


class WaitListSerializer(serializers.ModelSerializer):
    class Meta:
        model = WaitList
        # fields = ['first_name', 'last_name', 'practice_name', 'email']
        fields = "__all__"
