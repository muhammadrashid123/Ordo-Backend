import asyncio
import os

from apps.vendor_clients.sync_clients import BaseClient


def get_config(vendor_slug: str):
    configs = {
        "henry_schein": {
            "username": os.getenv("HENRY_SCHEIN_USERNAME"),
            "password": os.getenv("HENRY_SCHEIN_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "2288210",
                        "url": "https://www.henryschein.com/us-en/dental/p"
                        "/anesthetics/injectables/septocaine-cart-4-w-epi/2288210",
                        "unit": "BX",
                    },
                    "quantity": 1,
                },
                {
                    "product": {
                        "product_id": "5430113",
                        "url": "https://www.henryschein.com/us-en/dental/p"
                        "/preventive/toothbrushes/wave-toothbrush/5430113",
                        "unit": "BX",
                    },
                    "quantity": 1,
                },
            ],
        },
        "net_32": {
            "username": os.getenv("NET32_USERNAME"),
            "password": os.getenv("NET32_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "101047",
                        "url": "",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
                {
                    "product": {
                        "product_id": "138937",
                        "url": "",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
            ],
        },
        "darby": {
            "username": os.getenv("DARBY_SCHEIN_USERNAME"),
            "password": os.getenv("DARBY_SCHEIN_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "9515480",
                        "url": "https://www.darbydental.com/categories/Anesthetics"
                        "/Injectable-Anesthetic/Septocaine-(Articaine-HCl-and-Epinephrine)/9515480",
                    },
                    "quantity": 1,
                }
            ],
        },
        "patterson": {
            "username": os.getenv("PATTERSON_USERNAME"),
            "password": os.getenv("PATTERSON_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "070215376",
                        "url": "https://www.pattersondental.com/Supplies/ItemDetail/070215376",
                    },
                    "quantity": 1,
                },
                {
                    "product": {
                        "product_id": "071110139",
                        "url": "https://www.pattersondental.com/Supplies/ItemDetail/071110139",
                    },
                    "quantity": 1,
                },
            ],
        },
        "ultradent": {
            "username": os.getenv("ULTRADENT_USERNAME"),
            "password": os.getenv("ULTRADENT_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "1431-",
                        "url": "https://www.pattersondental.com/Supplies/ItemDetail/071110139",
                    },
                    "quantity": 1,
                },
            ],
        },
        "benco": {
            "username": os.getenv("BENCO_USERNAME"),
            "password": os.getenv("BENCO_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "4556-394",
                        "url": "https://shop.benco.com/Product/2452-311"
                        "/periosonic-multi-fluid-irrigator#product-detail-tab",
                    },
                    "quantity": 1,
                },
            ],
        },
        "amazon": {
            "username": os.getenv("AMAZON_USERNAME"),
            "password": os.getenv("AMAZON_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "",
                        "url": "",
                    },
                    "quantity": 1,
                },
            ],
        },
        "implant_direct": {
            "username": os.getenv("IMPLANT_DIRECT_USERNAME"),
            "password": os.getenv("IMPLANT_DIRECT_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "",
                        "url": "https://store.implantdirect.com/g-sleeve-l.html",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
                {
                    "product": {
                        "product_id": "",
                        "url": "https://store.implantdirect.com/skg-l.html",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
            ],
        },
        "edge_endo": {
            "username": os.getenv("EDGE_ENDO_USERNAME"),
            "password": os.getenv("EDGE_ENDO_PASSWORD"),
        },
        "dental_city": {
            "username": os.getenv("DENTAL_CITY_USERNAME"),
            "password": os.getenv("DENTAL_CITY_PASSWORD"),
            "products": [
                {
                    "product": {
                        "product_id": "",
                        "url": "https://www.dentalcity.com/product/9233/ortho-direct-bond-buttons-round-base",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
                {
                    "product": {
                        "product_id": "",
                        "url": "https://www.dentalcity.com"
                        "/product/1072/septodont-cook-waite-lidocaine-hcl-2-epinephrine-1100000-50bx",
                        "product_unit": "",
                    },
                    "quantity": 1,
                },
            ],
        },
    }
    return configs[vendor_slug]


async def main():
    vendor_slug = os.getenv("DEBUG_VENDOR_SLUG")
    configs = get_config(vendor_slug)
    username = configs["username"]
    password = configs["password"]
    vendor_client: BaseClient = BaseClient.make_handler(vendor_slug, username, password)
    # results = vendor_client.get_orders()
    # results = vendor_client.confirm_order(configs["products"], fake=True)
    results = await vendor_client.get_products_prices(list(map(lambda x: x["product"], configs["products"])))
    print(results)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(main())
