import asyncio
import logging

from decimal import Decimal
from typing import Dict, List

from apps.scrapers.base import Scraper
from apps.types.orders import CartProduct
from apps.scrapers.schema import VendorOrderDetail


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class AmazonScraper(Scraper):

    BASE_URL = "https://www.amazon.com"

    async def create_order(self, products: List[CartProduct], shipping_method=None) -> Dict[str, VendorOrderDetail]:
        print("amazon/create_order")
        try:
            # Temporary raise an error
            await asyncio.sleep(0.3)
            raise Exception()
        except:
            print("amazon create_order except")
            subtotal_manual = sum([prod['price']*prod['quantity'] for prod in products])
            vendor_order_detail = VendorOrderDetail.from_dict(
                {
                    "retail_amount": 0,
                    "savings_amount": 0,
                    "subtotal_amount": Decimal(subtotal_manual),
                    "shipping_amount": 0,
                    "tax_amount": 0,
                    "total_amount": Decimal(subtotal_manual),
                    "payment_method": "",
                    "shipping_address": "",
                    "reduction_amount": Decimal(subtotal_manual),
                }
            )
        finally:
            vendor_slug: str = self.vendor.slug
            print("henryschein/create_order DONE")
            return {
                vendor_slug: {
                    **vendor_order_detail.to_dict(),
                    **self.vendor.to_dict(),
                },
            }

    async def confirm_order(self, products: List[CartProduct], shipping_method=None, fake=False, redundancy=False):
        print("amazon/confirm_order")