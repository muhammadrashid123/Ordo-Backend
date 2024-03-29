from rest_framework import response, status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.accounts.serializers import CouponCheckQuerySerializer
from apps.accounts.services import stripe


class CouponCheckView(APIView):
    http_method_names = ["get"]
    permission_classes = [AllowAny]

    def get(self, request):
        serializer = CouponCheckQuerySerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        coupon_data = stripe.get_coupon_data(serializer.validated_data["code"])
        if coupon_data is None:
            return response.Response({"error": "Coupon not found"}, status=status.HTTP_404_NOT_FOUND)
        return response.Response(coupon_data)
