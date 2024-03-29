from rest_framework import serializers

from apps.accounts.models import Company, Office, OfficeBudget, SubCompany


class OfficeBudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficeBudget
        fields = "__all__"


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = "__all__"


class SubCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCompany
        fields = "__all__"


class OfficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Office
        fields = "__all__"
