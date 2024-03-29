from rest_framework import mixins, response, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import Subaccount
from apps.accounts.serializers import SubaccountRemoveSerializer
from apps.orders.permissions import SubaccountPermission


class SubaccountViewSet(mixins.DestroyModelMixin, GenericViewSet):
    queryset = Subaccount.objects.all()
    permission_classes = [IsAuthenticated & SubaccountPermission]

    @action(detail=True, methods=["post"])
    def remove(self, request, *args, **kwargs):
        subaccount = self.get_object()
        serializer = SubaccountRemoveSerializer(data=request.data, context={"subaccount": subaccount})
        serializer.is_valid(raise_exception=True)
        OfficeBudgetHelper.remove_subaccount(subaccount, serializer.validated_data["substitute_slug"])
        return response.Response(status=status.HTTP_204_NO_CONTENT)
