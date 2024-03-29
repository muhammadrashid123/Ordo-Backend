# views.py
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .models import WaitList
from .serializers import WaitListSerializer


class WaitListCreateAPIView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    queryset = WaitList.objects.all()
    serializer_class = WaitListSerializer
