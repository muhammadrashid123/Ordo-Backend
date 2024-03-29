import asyncio
import logging
import os
import time
from decimal import Decimal
from enum import Enum
from typing import List, Union

import xmltodict
from aiohttp.client import ClientSession
from lxml import etree

from services.api_client.vendor_api_types import (
    DentalCityInvoiceDetail,
    DentalCityInvoiceProduct,
    DentalCityOrderDetail,
    DentalCityOrderInfo,
    DentalCityOrderProduct,
    DentalCityPartnerInfo,
    DentalCityProduct,
    DentalCityShippingInfo,
    DentalCityShippingProduct,
)
from services.utils.xml import dict2xml

logger = logging.getLogger(__name__)


class Stage(Enum):
    TEST = "https://dcservicestest.azurewebsites.net"
    PROD = "https://dcservices.azurewebsites.net"


XML_LANG = "en-US"


class DentalCityOrderRequestBuilder:
    def __init__(self, partner_info: DentalCityPartnerInfo, order_info: DentalCityOrderInfo):
        self.partner_info = partner_info
        self.order_info = order_info

    def build_header(self) -> dict:
        return {
            "From": {
                "Credential": {
                    "@domain": "NetworkId",
                    "Identity": self.partner_info.partner_name,
                }
            },
            "To": {
                "Credential": {
                    "@domain": "NetworkId",
                    "Identity": "DENTALCITY",
                }
            },
            "Sender": {
                "Credential": {
                    "@domain": "NetworkId",
                    "Identity": self.partner_info.partner_name,
                    "SharedSecret": self.partner_info.shared_secret,
                },
                "UserAgent": self.partner_info.partner_name,
            },
        }

    def build_products(self) -> list:
        return [
            {
                "@quantity": product.quantity,
                "@lineNumber": i + 1,
                "ItemID": {
                    "SupplierPartID": product.product_sku,
                },
                "ItemDetail": {
                    "UnitPrice": {
                        "Money": {
                            "@currency": "USD",
                            "#text": str(product.unit_price),
                        },
                    },
                    "Description": {"@xml:lang": "en", "#text": product.product_description},
                    "UnitOfMeasure": "Each",
                    "Classification": {
                        "@domain": "UNSPSC",
                        "#text": 0,
                    },
                    "ManufacturerPartID": product.manufacturer_part_number,
                },
                "Comments": {"@xml:lang": "en-US"},
            }
            for i, product in enumerate(self.order_info.order_products)
        ]

    def build_shipping_address(self) -> dict:
        return {
            "Address": {
                "@addressID": self.order_info.shipping_address.address_id,
                "Name": {
                    "@xml:lang": "en-US",
                    "#text": self.order_info.shipping_address.name,
                },
                "PostalAddress": {
                    "DeliverTo": self.order_info.shipping_address.deliver_to,
                    "Street": self.order_info.shipping_address.street,
                    "City": self.order_info.shipping_address.city,
                    "State": self.order_info.shipping_address.state,
                    "PostalCode": self.order_info.shipping_address.postal_code,
                    "Country": {
                        "@isoCountryCode": self.order_info.shipping_address.country_code,
                        "#text": self.order_info.shipping_address.country_name,
                    },
                },
                "Email": self.order_info.shipping_address.email,
                "Phone": {
                    "@name": "work",
                    "TelephoneNumber": {
                        "CountryCode": {
                            "@isoCountryCode": "US",
                            "#text": self.order_info.shipping_address.phone_number_country_code,
                        },
                        "AreaOrCityCode": "",
                        "Number": self.order_info.shipping_address.phone_number_national_number,
                    },
                },
            },
        }

    def build_billing_address(self) -> dict:
        return {
            "Address": {
                "@addressID": self.order_info.billing_address.address_id,
                "Name": {
                    "@xml:lang": "en-US",
                    "#text": self.order_info.billing_address.name,
                },
                "PostalAddress": {
                    "DeliverTo": self.order_info.billing_address.deliver_to,
                    "Street": self.order_info.billing_address.street,
                    "City": self.order_info.billing_address.city,
                    "State": self.order_info.billing_address.state,
                    "PostalCode": self.order_info.billing_address.postal_code,
                    "Country": {
                        "@isoCountryCode": self.order_info.billing_address.country_code,
                        "#text": self.order_info.billing_address.country_name,
                    },
                },
            }
        }

    def build_request(self):
        return {
            "@deploymentMode": "production",
            "OrderRequest": {
                "OrderRequestHeader": {
                    "@orderID": self.order_info.order_id,
                    "@orderDate": self.order_info.order_datetime_string,
                    "@type": "new",
                    "@orderType": "regular",
                    "Total": {
                        "Money": {
                            "@currency": "USD",
                            "#text": str(self.order_info.total_amount),
                        }
                    },
                    "ShipTo": self.build_shipping_address(),
                    "BillTo": self.build_billing_address(),
                    "Shipping": {
                        "Money": {
                            "@currency": "USD",
                            "#text": str(self.order_info.shipping_amount),
                        },
                        "Description": {
                            "@xml:lang": "en-US",
                            "#text": "UPS",
                        },
                    },
                    "Comments": {"@xml:lang": "en-US"},
                    "Extrinsic": {
                        "@name": "CustomerNumber",
                        "#text": self.partner_info.customer_id,
                    },
                },
                "ItemOut": self.build_products(),
            },
        }

    def build(self):
        dict_object = {
            "@payloadID": self.order_info.order_id,
            "@timestamp": f"{self.order_info.order_datetime_string}",
            "@xml:lang": XML_LANG,
            "@version": "1.2.011",
            "Header": self.build_header(),
            "Request": self.build_request(),
        }
        root = dict2xml(dict_object, element_name="cXML")
        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            doctype='<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.011/cXML.dtd">',
            pretty_print=True,
        ).decode()


class DentalCityAPIClient:
    def __init__(self, session: ClientSession, stage: Stage = Stage.PROD, auth_key: str = ""):
        self.session = session
        self.stage = stage
        self.page_size = 5000
        self.session.headers.update({"x-functions-key": auth_key})

    async def get_page_products(self, page_number: int = 1) -> List[DentalCityProduct]:
        url = f"{self.stage.value}/api/ProductPriceStockAvailability"
        params = {
            "page_size": self.page_size,
            "page_number": page_number,
        }
        async with self.session.get(url, params=params) as resp:
            if resp.status == 200:
                products = await resp.json()
                if products:
                    return [DentalCityProduct.from_dict(product) for product in products]

    async def get_products(self) -> List[DentalCityProduct]:
        products: List[DentalCityProduct] = []
        start_page = 1
        while True:
            end_page = start_page + 10
            tasks = (self.get_page_products(page) for page in range(start_page, end_page))
            results = await asyncio.gather(*tasks)
            for result in results:
                if result is None:
                    continue
                products.extend(result)
            if len(products) < self.page_size * (end_page - 1):
                break
            start_page = end_page
            # TODO: asyncio.sleep(10)
            time.sleep(10)
        return products

    async def create_order_request(self, partner_info: DentalCityPartnerInfo, order_info: DentalCityOrderInfo) -> bool:
        url = f"{self.stage.value}/api/OrderRequest"
        builder = DentalCityOrderRequestBuilder(partner_info, order_info)
        body = builder.build()
        logger.debug("Sending requst to %s: %s", url, body)
        async with self.session.post(url, data=body) as resp:
            response_text = await resp.text()
            logger.info("Order request returned status code %s, body: %s", resp.status, response_text)
            return resp.status == 200


class DentalCityCXMLParser:
    @staticmethod
    def xml2dict(xml_content: Union[str, dict]):
        if isinstance(xml_content, str):
            xml_dict = xmltodict.parse(xml_content)
        else:
            xml_dict = xml_content
        return xml_dict

    @staticmethod
    def parse_order_response(xml_content: Union[str, dict]) -> str:
        xml_dict = DentalCityCXMLParser.xml2dict(xml_content)
        return xml_dict["cXML"]["@payloadID"]

    @staticmethod
    def parse_confirm_request(xml_content) -> DentalCityOrderDetail:
        xml_dict = DentalCityCXMLParser.xml2dict(xml_content)
        confirmation_request = xml_dict["cXML"]["Request"]["ConfirmationRequest"]
        order_id = confirmation_request["OrderReference"]["@orderID"]
        confirmation_header = confirmation_request["ConfirmationHeader"]
        vendor_order_id = confirmation_header["@confirmID"]
        total_amount = Decimal(confirmation_header["Total"]["Money"]["#text"])
        tax_amount = Decimal(confirmation_header["Tax"]["Money"]["#text"])
        shipping_amount = Decimal(confirmation_header["Shipping"]["Money"]["#text"])
        confirmation_items = confirmation_request["ConfirmationItem"]
        if isinstance(confirmation_items, dict):
            confirmation_items = [confirmation_items]
        order_products = []
        for item in confirmation_items:
            confirmation_status = item["ConfirmationStatus"]
            order_products.append(
                DentalCityOrderProduct(
                    product_sku=confirmation_status["Extrinsic"]["#text"],
                    unit_price=Decimal(confirmation_status["UnitPrice"]["Money"]["#text"]),
                    quantity=int(confirmation_status["@quantity"]),
                    manufacturer_part_number="",
                    product_description="",
                )
            )

        return DentalCityOrderDetail(
            order_id=order_id,
            vendor_order_id=vendor_order_id,
            total_amount=total_amount,
            tax_amount=tax_amount,
            shipping_amount=shipping_amount,
            order_products=order_products,
        )

    @staticmethod
    def parse_shipment_notice_request(xml_content) -> DentalCityShippingInfo:
        xml_dict = DentalCityCXMLParser.xml2dict(xml_content)
        ship_notice = xml_dict["cXML"]["Request"]["ShipNoticeRequest"]
        ship_notice_portion = ship_notice["ShipNoticePortion"]
        order_id = ship_notice_portion["OrderReference"]["@orderID"]
        payload_id = ship_notice_portion["OrderReference"]["DocumentReference"]["@payloadID"]
        carrier = ship_notice_portion["OrderReference"]["DocumentReference"]["@payloadID"]
        shipment_identifier = ship_notice["ShipControl"]["CarrierIdentifier"]["#text"]
        shipping_items = ship_notice_portion["ShipNoticeItem"]
        if not isinstance(shipping_items, list):
            shipping_items = [shipping_items]

        shipping_products = []
        for item in shipping_items:
            shipping_products.append(
                DentalCityShippingProduct(product_sku=item["ItemID"]["SupplierPartID"], quantity=item["@quantity"])
            )
        return DentalCityShippingInfo(
            order_id=order_id,
            payload_id=payload_id,
            carrier=carrier,
            shipment_identifier=shipment_identifier,
            shipping_products=[],
        )

    @staticmethod
    def parse_invoice_detail_request(xml_content) -> DentalCityInvoiceDetail:
        xml_dict = DentalCityCXMLParser.xml2dict(xml_content)
        invoice_detail_request = xml_dict["cXML"]["Request"]["InvoiceDetailRequest"]
        invoice_detail = invoice_detail_request["InvoiceDetailOrder"]
        invoice_detail_summary = invoice_detail_request["InvoiceDetailSummary"]
        invoice_product_items = invoice_detail["InvoiceDetailItem"]
        payload_id = xml_dict["cXML"]["@payloadID"]
        order_id = invoice_detail["InvoiceDetailOrderInfo"]["OrderReference"]["@orderID"]
        invoice_id = invoice_detail_request["InvoiceDetailRequestHeader"]["@invoiceID"]
        total_amount = invoice_detail_summary["GrossAmount"]["Money"]["#text"]
        tax_amount = invoice_detail_summary["Tax"]["Money"]["#text"]
        shipping_amount = invoice_detail_summary["ShippingAmount"]["Money"]["#text"]

        if not isinstance(invoice_product_items, list):
            invoice_product_items = [invoice_product_items]

        invoice_products = []
        for item in invoice_product_items:
            invoice_products.append(
                DentalCityInvoiceProduct(
                    product_sku=item["InvoiceDetailItemReference"]["ItemID"]["SupplierPartID"],
                    unit_price=item["UnitPrice"]["Money"]["#text"],
                    total_price=item["GrossAmount"]["Money"]["#text"],
                )
            )

        return DentalCityInvoiceDetail(
            payload_id=payload_id,
            order_id=order_id,
            invoice_id=invoice_id,
            total_amount=total_amount,
            tax_amount=tax_amount,
            shipping_amount=shipping_amount,
            invoice_products=invoice_products,
        )


async def main():
    async with ClientSession() as session:
        api_client = DentalCityAPIClient(session, stage=Stage.TEST, auth_key=os.environ.get("DENTAL_CITY_AUTH_KEY"))
        return await api_client.get_products()


if __name__ == "__main__":
    asyncio.run(main())
