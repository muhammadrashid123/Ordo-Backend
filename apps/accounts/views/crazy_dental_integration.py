import logging

import requests
from django.http import HttpResponse
from requests_oauthlib import OAuth1
from rest_framework import status
from rest_framework.views import APIView

from apps.accounts.models import OfficeVendor
from apps.api_integration.models import IntegrationClientDetails

logger = logging.getLogger(__name__)

consumer_key = "8e7899b9700566e362175d8159bbe176f015d362bd47b1e35792950539eef3a8"
consumer_secret = "3caa932e18ebc78cb4d1580f5ccbc8829ce465fe2937b4aa3703238c4dfbdf60"
access_token = "65ee54eedc16fc2040198f61cbc5e382c8ff9e6f5ee383c94c81b8a93e232a34"
token_secret = "726843e26ed822a03f90597e55c9c997d18e0c566cec9e1de6a4be11362821ba"
realm = 1075085
crazy_dental_Base_url = "https://1075085.restlets.api.netsuite.com/app/site/hosting/restlet.nl"
url = crazy_dental_Base_url
crazy_dental_username = "alex@joinordo.com"
crazy_dental_password = "#ordotest1"
crazy_dental_ordo_vendor_id = 12
crazy_dental_customer_service_email = [
    "ordo@dcdental.com",
    "muhammad.rashid@utordigital.com",
    "daniyal.ali@utordigital.com",
    "mrashid6695@gmail.com",
]

oauth = OAuth1(
    client_key=consumer_key,
    client_secret=consumer_secret,
    resource_owner_key=access_token,
    resource_owner_secret=token_secret,
    realm=realm,
    signature_method="HMAC-SHA256",
)
headers = {"Content-Type": "application/json"}


def get_vendor_customer_id(office_id):
    customer_obj = IntegrationClientDetails.objects.filter(office_id=office_id).first()
    if customer_obj:
        return customer_obj.vendor_customer_number


class CreateCustomerAPIView(APIView):
    def create_api_client_details(self, office_id, vendor_customer_number):
        api_client_details = IntegrationClientDetails.objects.create(
            office_id=office_id, vendor_customer_number=vendor_customer_number
        )

        return api_client_details

    def create_customer(self, office_id, customer_info):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
        }

        response = requests.post(url, params=params, json=customer_info, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return None

        result = response.json()
        if result["success"]:
            self.create_api_client_details(office_id=office_id, vendor_customer_number=result["result"])
            return result["result"]

    def get_customer(self, email: str):
        params = {
            "script": "customscript_pri_rest_customer",
            "deploy": "customdeploy_pri_rest_customer_ordo4837",
            "email": email,
        }
        response = requests.get(url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return []

        result = response.json()
        if result["success"]:
            return result["result"]

    def get_or_create_customer_id(self, office_id, office_email, customer_data):
        customer_info = self.get_customer(office_email)
        if customer_info:
            return customer_info[0]["internalid"]
        else:
            return self.create_customer(office_id, customer_data)

    def post(self, request):
        office_id = request.query_params.get("office_id")
        vendor_id = request.query_params.get("vendor_id")
        office_vendor_obj = OfficeVendor.objects.filter(office_id=office_id, vendor_id=vendor_id).first()
        if office_vendor_obj:
            # office_address = office_vendor_obj.office.addresses.first()
            office_email = office_vendor_obj.username
            customer_data = {
                "body": {
                    "entitystatus": "13",
                    "entityid": f"{office_vendor_obj.office.name} {office_vendor_obj.office.phone_number}",
                    "companyname": office_vendor_obj.office.name,
                    "phone": str(office_vendor_obj.office.phone_number),
                    "externalid": office_vendor_obj.id,
                    "email": office_email,
                }
            }
            customer_id = self.get_or_create_customer_id(office_id, office_email, customer_data)
            print("customer_id  ========================", type(customer_id))
            return HttpResponse(customer_id, content_type="application/json")
        return HttpResponse("Something went wrong", content_type="application/json")


class UserAddressListCreateAPIView(APIView):
    def get(self, request):
        address = []
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)
        if customer_id:
            params = {
                "script": "customscript_pri_rest_customer_address",
                "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
                "customerid": customer_id,
            }

            response = requests.get(url, params=params, headers=headers, auth=oauth)
            if response.status_code != status.HTTP_200_OK:
                return HttpResponse(None, content_type="application/json")

            result = response.json()
            if result["success"]:
                address.append(result)
                return HttpResponse(address, content_type="application/json")
        else:
            return HttpResponse(None, content_type="application/json")

    def post(self, request):
        data = request.data
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
        }
        customer_address_data = {
            "parameters": {"customerid": customer_id},
            "body": {
                "defaultbilling": data.get("defaultbilling"),
                "defaultshipping": data.get("defaultshipping"),
                "addressee": data.get("addressee"),
                "attention": data.get("attention"),
                "city": data.get("city"),
                "state": data.get("state"),
                "country": data.get("country"),
                "zip": data.get("zip"),
                "addr1": data.get("addr1"),
            },
        }
        response = requests.post(url, params=params, json=customer_address_data, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse(None, content_type="application/json")

        result = response.json()
        if result["success"]:
            return HttpResponse(result["result"], content_type="application/json")

    def put(self, request):
        data = request.data
        address_id = request.query_params.get("address_id")
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
        }
        customer_address_data = {
            "parameters": {"customerid": customer_id, "addressid": address_id},
            "body": {
                "defaultbilling": data.get("defaultbilling"),
                "defaultshipping": data.get("defaultshipping"),
                "addressee": data.get("addressee"),
                "attention": data.get("attention"),
                "city": data.get("city"),
                "state": data.get("state"),
                "country": data.get("country"),
                "zip": data.get("zip"),
                "addr1": data.get("addr1"),
            },
        }

        response = requests.put(url, params=params, json=customer_address_data, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse(None, content_type="application/json")

        result = response.json()
        if result["success"]:
            return HttpResponse(result["result"], content_type="application/json")


class DCDentalCreditCardView(APIView):
    def get(self, request):
        card_list = []
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)

        params = {
            "script": "customscript_pri_rest_customer_cc",
            "deploy": "customdeploy_pri_rest_cust_cc_ordo4837",
            "customerid": customer_id,
        }

        response = requests.get(url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse(None, content_type="application/json")

        result = response.json()
        if result["success"]:
            card_list.append(result)
            return HttpResponse(card_list, content_type="application/json")

    def post(self, request):
        data = request.data
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)
        params = {
            "script": "customscript_pri_rest_customer_cc",
            "deploy": "customdeploy_pri_rest_cust_cc_ordo4837",
        }
        payment_method = data.get("ccnumber")[0]

        parts = data.get("ccexpiredate").split("/")
        ccexpiredate = parts[0] + "/01/" + parts[1]
        customer_address_data = {
            "parameters": {"customerid": customer_id},
            "body": {
                "ccname": data.get("ccname"),
                "ccmemo": data.get("ccmemo"),
                "ccnumber": data.get("ccnumber"),
                "ccexpiredate": ccexpiredate,
                "ccdefault": True,
                "customercode": data.get("customercode"),
                "debitcardissueno": data.get("debitcardissueno"),
                "paymentmethod": payment_method,
                "statefrom": data.get("statefrom"),
                "validfrom": data.get("validfrom"),
            },
        }

        response = requests.post(url, params=params, json=customer_address_data, headers=headers, auth=oauth)

        result = response.json()
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse("Something went wrong", content_type="application/json")

        if result["success"]:
            return HttpResponse(result["result"], content_type="application/json")
        return HttpResponse(result["exception"]["message"], content_type="application/json")

    def delete(self, request):
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)

        params = {
            "script": "customscript_pri_rest_customer_cc",
            "deploy": "customdeploy_pri_rest_cust_cc_ordo4837",
            "customerid": customer_id,
            "ccid": request.query_params.get("ccid"),
        }

        response = requests.delete(url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse(None, content_type="application/json")

        result = response.json()
        if result["success"]:
            return HttpResponse(result["result"], content_type="application/json")

    def put(self, request):
        data = request.data
        office_id = request.query_params.get("office_id")
        customer_id = get_vendor_customer_id(office_id=office_id)

        params = {"script": "customscript_pri_rest_customer_cc", "deploy": "customdeploy_pri_rest_cust_cc_ordo4837"}

        customer_address_data = {
            "parameters": {"customerid": customer_id, "ccid": request.query_params.get("ccid")},
            "body": {
                "ccname": data.get("ccname"),
                "ccmemo": data.get("ccmemo"),
                "ccnumber": data.get("ccnumber"),
                "ccexpiredate": data.get("ccexpiredate"),
                "ccdefault": data.get("ccdefault"),
                "customercode": data.get("customercode"),
                "debitcardissueno": data.get("debitcardissueno"),
                "paymentmethod": data.get("paymentmethod"),
                "statefrom": data.get("statefrom"),
                "validfrom": data.get("validfrom"),
            },
        }

        response = requests.put(url, params=params, json=customer_address_data, headers=headers, auth=oauth)

        result = response.json()
        if response.status_code != status.HTTP_200_OK:
            return HttpResponse("Something went wrong", content_type="application/json")

        if result["success"]:
            return HttpResponse(result["result"], content_type="application/json")
        return HttpResponse(result["exception"]["message"], content_type="application/json")
