from rest_framework.views import APIView
from rest_framework import permissions, response, status
from . import serializers

class ReportBadUrl(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, format=None):
        serializer = serializers.BadImageUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return response.Response(status=status.HTTP_204_NO_CONTENT)