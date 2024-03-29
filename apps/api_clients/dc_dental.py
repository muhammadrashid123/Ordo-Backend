import logging
from typing import List

from apps.accounts.models import (  # IntegrationClientDetails,
    CompanyMember,
    OfficeVendor,
    User,
)

# from apps.api_integration.models import IntegrationClientDetails
from apps.orders.models import VendorOrder
from apps.types.orders import CartProduct
from services.api_client import DCDentalAPIClient

logger = logging.getLogger(__name__)


class DCDentalClient:
    def __init__(self, session):
        self.api_client = DCDentalAPIClient(session=session)

    async def get_or_create_customer_id(self, email, customer_data):
        customer_info = await self.api_client.get_customer(email)
        if customer_info:
            return customer_info[0]["internalid"]
        else:
            return await self.api_client.create_customer(customer_data)

    async def get_or_create_customer_address(self, customer_id, customer_address_data):
        customer_address_info = await self.api_client.get_customer_address(customer_id)
        if customer_address_info[0]["addressinternalid"]:
            return customer_address_info[0]["addressinternalid"]
        else:
            customer_address_info = await self.api_client.create_customer_address(customer_address_data)
            return customer_address_info["addressid"]

    # async def create_api_client_details(self, office_id, vendor_customer_name):
    #     api_client_details = await IntegrationClientDetails.objects.create(
    #         office_id=office_id, vendor_customer_name=vendor_customer_name
    #     )
    #
    #     return api_client_details

    async def place_order(self, office_vendor: OfficeVendor, vendor_order: VendorOrder, products: List[CartProduct]):
        office = office_vendor.office
        office_address = office_vendor.office.addresses.first()
        office_admin = (
            await CompanyMember.objects.filter(company=office_vendor.office.company, role=User.Role.ADMIN)
            .select_related("user")
            .afirst()
        )
        office_email = office_vendor.username

        office_phone_number = office.phone_number.raw_input
        customer_data = {
            "body": {
                "entitystatus": "13",
                "entityid": f"{office.name} {office_phone_number}",
                "companyname": office.name,
                "phone": office_phone_number,
                "externalid": office_vendor.id,
                "email": office_email,
            }
        }
        customer_id = await self.get_or_create_customer_id(office_email, customer_data)
        customer_address_data = {
            "parameters": {"customerid": customer_id},
            "body": {
                "defaultbilling": True,
                "defaultshipping": False,
                "addressee": office.name,
                "attention": f"{office_admin.user.first_name} {office_admin.user.last_name}",
                "city": office_address.city,
                "state": office_address.state,
                "country": "US",
                "zip": office_address.zip_code,
                "addr1": office_address.address,
            },
        }
        customer_address = await self.get_or_create_customer_address(customer_id, customer_address_data)
        # office = office_vendor.office.id.first()
        # print("office id +++++++++++++++++++++++++++++++++++++++++", office)
        # print("office address office id ++++++++++++++++++++++", office_address.office_id)
        # save_customer_id = await self.create_api_client_details(
        #     office_id=office_address.office_id, vendor_customer_name=customer_id
        # )
        # print(save_customer_id)
        order_info = {
            "body": {
                "entity": customer_id,
                "trandate": vendor_order.created_at.strftime("%m/%d/%Y"),
                "otherrefnum": str(vendor_order.id),
                "shipaddresslist": customer_address,
                "billaddresslist": customer_address,
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
        vendor_order.vendor_order_id = result
        await vendor_order.asave()
