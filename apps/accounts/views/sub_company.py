from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts import models as m
from apps.accounts import serializers as s


class SubCompanyViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    GenericViewSet,
):
    queryset = m.SubCompany.objects.all()
    serializer_class = s.SubCompanySerializer

    def get_queryset(self):
        return self.queryset.filter(company_id=self.kwargs["company_pk"])

    @action(detail=False, methods=["GET"], url_path="get_all_sub_companies")
    def get_all_sub_companies(self, request, company_pk=None, slug=None):
        try:
            sub_companies = self.get_queryset()
            serializer = s.SubCompanySerializer(sub_companies, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except m.SubCompany.DoesNotExist:
            return Response({"error": "SubCompany not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["GET"], url_path="get_sub_company")
    def get_sub_company(self, request, *args, **kwargs):
        try:
            sub_company = self.queryset.get(id=request.query_params["sub_company"])
            serializer = s.SubCompanySerializer(sub_company, many=False)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except m.SubCompany.DoesNotExist:
            return Response({"error": "SubCompany not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["DELETE"], url_path="remove_sub_company")
    def remove_sub_company(self, request, *args, **kwargs):
        try:
            sub_company_id = request.data.get("sub_company")
            sub_company = self.queryset.get(id=sub_company_id)
            sub_company.delete()
            serializer = s.SubCompanySerializer(self.get_queryset(), many=True)
            return Response(serializer.data, status=status.HTTP_205_RESET_CONTENT)
        except m.SubCompany.DoesNotExist:
            return Response({"error": "SubCompany not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["PUT"], url_path="update_sub_company")
    def update_sub_company(self, request, *args, **kwargs):
        try:
            sub_company_id = request.data.get("sub_company")
            sub_company_instance = m.SubCompany.objects.get(pk=sub_company_id)
            serializer = s.SubCompanySerializer(sub_company_instance, data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except m.SubCompany.DoesNotExist:
            return Response({"error": "SubCompany not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["POST"], url_path="add_new_sub_company")
    def add_new_sub_company(self, request, company_pk=None):
        try:
            mutable_data = request.data.copy()
            mutable_data['creator'] = request.user.id
            serializer = s.SubCompanySerializer(data=mutable_data)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except m.SubCompany.DoesNotExist:
            return Response({"error": "SubCompany not found"}, status=status.HTTP_404_NOT_FOUND)
