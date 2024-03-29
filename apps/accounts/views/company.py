import requests
from django.db import IntegrityError, transaction
from requests_oauthlib import OAuth1
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts import models as m
from apps.accounts import permissions as p
from apps.accounts import serializers as s
from apps.accounts.models import Office, OfficeVendor, Vendor
from apps.accounts.services.offices import OfficeService
from apps.accounts.views.crazy_dental_integration import (
    access_token,
    consumer_key,
    consumer_secret,
    crazy_dental_Base_url,
    crazy_dental_ordo_vendor_id,
    crazy_dental_password,
    realm,
    token_secret,
)
from apps.api_integration.models import IntegrationClientDetails

oauth = OAuth1(
    client_key=consumer_key,
    client_secret=consumer_secret,
    resource_owner_key=access_token,
    resource_owner_secret=token_secret,
    realm=realm,
    signature_method="HMAC-SHA256",
)
headers = {"Content-Type": "application/json"}


class CompanyViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    GenericViewSet,
):
    permission_classes = [p.CompanyOfficePermission]
    queryset = m.Company.objects.filter(is_active=True)
    serializer_class = s.CompanySerializer

    def create_api_client_details(self, office_id, vendor_customer_number):
        try:
            api_client_details = IntegrationClientDetails.objects.create(
                office_id=office_id, vendor_customer_number=vendor_customer_number
            )
            # Update OfficeVendor records for the current integration client
            OfficeVendor.objects.filter(office_id=office_id, vendor_id=crazy_dental_ordo_vendor_id).update(
                username=vendor_customer_number
            )
        except IntegrityError as e:
            print(f"Error creating IntegrationClientDetails: {e}")
            transaction.rollback()
            api_client_details = None
        return api_client_details

    def create_customer(self, office_id, customer_info):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
        }

        response = requests.post(
            url=crazy_dental_Base_url, params=params, json=customer_info, headers=headers, auth=oauth
        )
        if response.status_code != status.HTTP_200_OK:
            return None

        result = response.json()
        if result["success"]:
            self.create_api_client_details(office_id=office_id, vendor_customer_number=result["result"])
            return result["result"]

    def get_customer(self, office_id: str):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
            "internalid": office_id,
        }
        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return []

        result = response.json()
        if result["success"]:
            return result["result"]

    def get_or_create_customer_id(self, office_id, customer_data):
        customer_info = self.get_customer(office_id)
        if customer_info:
            return customer_info[0]["internalid"]
        else:
            return self.create_customer(office_id, customer_data)

    def crazy_dental_customer_creations(self, office_id, vendor_id):
        office_vendor_obj = OfficeVendor.objects.filter(office_id=office_id, vendor_id=vendor_id).first()
        if office_vendor_obj:
            customer_data = {
                "body": {
                    "entitystatus": "13",
                    "entityid": f"{office_vendor_obj.office.name} {office_vendor_obj.office.phone_number}",
                    "companyname": office_vendor_obj.office.name,
                    "phone": str(office_vendor_obj.office.phone_number),
                    "externalid": office_id,
                }
            }
            customer_id = self.get_or_create_customer_id(office_id, customer_data)
            return customer_id
        return None

    def update(self, request, *args, **kwargs):
        kwargs.setdefault("partial", True)
        company_id = self.get_object().pk
        response = super().update(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            if "on_boarding_step" in request.data:
                if request.data["on_boarding_step"] == 2:
                    return response
                elif request.data["on_boarding_step"] == 3:
                    return response
                else:
                    if request.data["on_boarding_step"] == 1:
                        try:
                            # office_name = request.data["offices"][0]["name"]
                            # print("office_name", office_name)
                            office = Office.objects.filter(company_id=company_id).latest("created_at")
                        except Office.DoesNotExist:
                            office = None

                        vendor_instance = Vendor.objects.filter(id=crazy_dental_ordo_vendor_id).first()

                        office_vendor_data = {
                            "username": "ordo",
                            "password": crazy_dental_password,
                            "vendor": vendor_instance,
                            "office": office,
                            "company_id": self.get_object().pk,
                        }
                        OfficeVendor.objects.create(**office_vendor_data)
                        customer_id = self.crazy_dental_customer_creations(
                            office_id=office.id, vendor_id=vendor_instance.id
                        )
                        if customer_id:
                            return response
                        else:
                            return response
                    else:
                        return response
            return response
        return response

    @action(detail=False, methods=["get"], url_path="onboarding-step")
    def get_company_on_boarding_step(self, request):
        company_member = m.CompanyMember.objects.filter(user=request.user).first()
        if company_member:
            return Response({"on_boarding_step": company_member.company.on_boarding_step})
        else:
            return Response({"message": ""})

    @action(detail=True, methods=["get"])
    def onboarding_status(self, request, *args, **kwargs):
        status = m.OnboardingStatus.get_for_company(company_id=self.get_object().pk)
        serializer = s.OnboardingStatusSerializer(instance=status)
        return Response(data=serializer.data)

    @onboarding_status.mapping.patch
    def update_onboarding_status(self, request, *args, **kwargs):
        status = m.OnboardingStatus.get_for_company(company_id=self.get_object().pk)
        serializer = s.OnboardingStatusSerializer(instance=status, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(data=serializer.data)

    def perform_destroy(self, instance):
        with transaction.atomic():
            active_members = m.CompanyMember.objects.all()
            for active_member in active_members:
                active_member.is_active = False

            m.CompanyMember.objects.bulk_update(active_members, ["is_active"])
            instance.is_active = False
            instance.save()

            for office in instance.offices.all():
                OfficeService.cancel_subscription(office)
