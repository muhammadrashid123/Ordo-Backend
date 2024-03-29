import logging
from typing import List, Optional

import requests
from asgiref.sync import sync_to_async
from rest_framework import status

from apps.accounts.models import OfficeVendor
from apps.accounts.views.crazy_dental_integration import (
    crazy_dental_Base_url,
    get_vendor_customer_id,
    oauth,
)
from apps.orders.models import VendorOrder
from apps.types.orders import CartProduct
from services.api_client.crazy_dental import CrazyDentalAPIClient

logger = logging.getLogger(__name__)


class CrazyDentalNewClient:
    def __init__(self, **kwargs):
        session = kwargs.get("session")
        vendor = kwargs.get("vendor")
        self.api_client = CrazyDentalAPIClient(session=session, vendor=vendor)

    async def get_customer_address(self, customer_id):
        headers = {"Content-Type": "application/json"}
        params = {
            "script": "customscript_pri_rest_customer_address",
            "deploy": "customdeploy_pri_rest_cust_add_ordo4837",
            "customerid": customer_id,
        }

        response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
        if response.status_code != status.HTTP_200_OK:
            return None

        result = response.json()
        if result["success"]:
            return result["result"]

    async def place_order(self, office_vendor: OfficeVendor, vendor_order: VendorOrder, products: List[CartProduct]):
        office = office_vendor.office

        get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
        customer_id = await get_vendor_customer_id_async(office_id=office)

        print("customer_id========", customer_id)
        customer_address_info = await self.get_customer_address(customer_id)
        print("customer_address_info", customer_address_info)
        try:
            address_internal_id = customer_address_info[0]["addressinternalid"]
            print("address_internal_id===================", address_internal_id)
        except TypeError:
            address_internal_id = None
            print("Customer address information is None.")

        # address_internal_id = customer_address_info[0]["addressinternalid"]
        print("address_internal_id", address_internal_id)
        order_info = {
            "body": {
                "entity": customer_id,
                "trandate": vendor_order.created_at.strftime("%m/%d/%Y"),
                "otherrefnum": str(vendor_order.id),
                "shipaddresslist": address_internal_id,
                "billaddresslist": address_internal_id,
                "items": [
                    {
                        "itemid": product["sku"],
                        "quantity": product["quantity"],
                        "rate": product["price"] if product["price"] else 0,
                    }
                    for product in products
                ],
            }
        }
        result = await self.api_client.create_order_request(order_info)
        print("=================result=======", result)
        vendor_order.vendor_order_id = result
        await vendor_order.asave()

    async def get_orders(
        self,
        office=None,
        completed_order_ids: Optional[List[str]] = None,
    ):
        print("Getting orders...")
        await self.api_client.get_crazy_dental_orders(office, completed_order_ids)
