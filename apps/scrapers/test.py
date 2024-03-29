import asyncio
import os
from enum import IntEnum, auto

from aiohttp import ClientSession, ClientTimeout

from apps.common.enums import SupportedVendor
from apps.scrapers.tests.factories import InvoiceInfoFactory
from apps.types.orders import CartProduct


def get_testing_data():
    return {
        SupportedVendor.HenrySchein: {
            "username": os.getenv("HENRY_SCHEIN_USERNAME"),
            "password": os.getenv("HENRY_SCHEIN_PASSWORD"),
            "products": [
                # {
                #     "product_id": "3840072",
                #     "product_url": "https://www.henryschein.com/us-en/dental/p/restorative-cosmetic"
                #     "/articulating/articulating-paper-40-microns/3840072",
                #     "quantity": 20,
                # },
                {"product_id": "1045452", "quantity": 1, "product_unit": "BX"},
                {"product_id": "3780394", "quantity": 1, "product_unit": "EA"},
                {"product_id": "1280024", "quantity": 1, "product_unit": "BX"},
                {"product_id": "3780386", "quantity": 1, "product_unit": "PK"},
                {"product_id": "9004578", "quantity": 3, "product_unit": "PK"},
                # {"product_id": "1126865", "quantity": 1, "product_unit": ""},
                # {"product_id": "1019278", "quantity": 6, "product_unit": ""},
                # {"product_id": "5430154", "quantity": 2, "product_unit": ""},
                # {"product_id": "5430262", "quantity": 2, "product_unit": ""},
                # {"product_id": "7740131", "quantity": 2, "product_unit": ""},
                # {"product_id": "1073642", "quantity": 2, "product_unit": ""},
                # {"product_id": "1127015", "quantity": 5, "product_unit": ""},
                # {"product_id": "7211022", "quantity": 1, "product_unit": ""},
                # {"product_id": "2220860", "quantity": 1, "product_unit": ""},
                # {"product_id": "1014060", "quantity": 1, "product_unit": ""},
                # {
                #     "product_id": "4434033",
                #     "product_url": "https://www.henryschein.com/us-en/dental/p/infection-control-products"
                #     "/protective-eyewear/visor-shield-kit-medium/4434033",
                #     "quantity": 1,
                # },
                # {
                #     "product_id": "5430231",
                #     "product_url": "https://www.henryschein.com/us-en/dental/p/preventive"
                #     "/toothbrushes/colgate-pj-masks-toothbrush/5430231",
                #     "quantity": 10,
                # },
            ],
            "invoice_data": {
                "invoice_link": "https://www.henryschein.com/us-en/olp/invoiceloading.aspx?"
                "type=inv&invoice_num=heg4aI8Rub%2fAnEirOka%2fd0Tq1OxDkVSdtOP%2bf344g18%3d",
            },
        },
        SupportedVendor.Net32: {
            "username": os.getenv("NET32_USERNAME"),
            "password": os.getenv("NET32_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.net32.com/account/orders/invoice/35222736",
                "order_id": "35222736",
            },
            "products": [
                # {
                #     "product_id": "113866",
                #     "product_url": "https://www.net32.com/ec/house-brand-premium-nitrile-exam-gloves-small-d-113866",
                #     "quantity": 1,
                # },
                # {
                #     "product_id": "149881",
                #     "product_url": "https://www.net32.com/ec/caviwipes-12-towelettes-large-6-x-675-d-149881",
                #     "quantity": 1,
                # },
                {
                    "product_id": "101047",
                    "quantity": 1,
                },
                {
                    "product_id": "147024",
                    "quantity": 1,
                },
                {
                    "product_id": "138937",
                    "quantity": 1,
                },
                {
                    "product_id": "40817",
                    "quantity": 1,
                },
            ],
        },
        SupportedVendor.Darby: {
            "username": os.getenv("DARBY_USERNAME"),
            "password": os.getenv("DARBY_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.darbydental.com/scripts/invoicedownload.ashx?"
                "invno=9743471&id=416135630f1df27f297dba23b80f2227edf78a73cffec84448dd70d90ee7f4a4",
            },
            "products": [
                {
                    "product_id": "323-3644",
                    "product_url": "https://www.darbydental.com/categories/Infection-Control"
                    "/Sterilization-Bags--Pouches--and-Tubing/CSR-Sterilization-Wrap/3233644",
                    "quantity": 1,
                },
                {
                    "product_id": "5250698",
                    "product_url": "https://www.darbydental.com/categories/Preventive-Products"
                    "/Toothbrushes/Oral-B-Orthodontic-Brush/5250698",
                    "quantity": 1,
                },
            ],
        },
        SupportedVendor.Patterson: {
            "username": os.getenv("PATTERSON_USERNAME"),
            "password": os.getenv("PATTERSON_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.pattersondental.com/DocumentLibrary/Invoice?"
                "invoiceNumber=3018684279&customerNumber=410201838",
            },
            "products": [
                {
                    "product_id": "PIF_63718",
                    "product_url": "https://www.pattersondental.com/Supplies/ProductFamilyDetails/PIF_63718?mc=0",
                },
                {
                    "product_id": "PIF_857369",
                    "product_url": "https://www.pattersondental.com/Supplies/ItemDetail/071110139",
                },
            ],
        },
        SupportedVendor.UltraDent: {
            "username": os.getenv("ULTRADENT_USERNAME"),
            "password": os.getenv("ULTRADENT_PASSWORD"),
            "invoice_data": {"invoice_link": "", "order_id": "11678713"},
            "cart_products": [
                CartProduct(
                    product_id="1019278",
                    product_unit="PK",
                    product_url="https://www.henryschein.com/us-en/dental/p/preventive/prophy-angles/acclean-disp-proph\
                        y-angle-lf/1045452",
                    quantity=1,
                    price=3.09,
                )
            ],
        },
        SupportedVendor.Benco: {
            "username": os.getenv("BENCO_USERNAME"),
            "password": os.getenv("BENCO_PASSWORD"),
            "invoice_data": {"invoice_link": "https://shop.benco.com/PurchaseHistory/InvoicePDFByInvoiceNum/1R763393"},
            "products": [
                # {
                #     "product_id": "2127-717",
                #     "product_url": "https://shop.benco.com/Product/2127-717/turbosensor-ultrasonic-scaler",
                #     "quantity": 2,
                # },
                # {
                #     "product_id": "2452-311",
                #     "product_url": "https://shop.benco.com/Product/2452-311"
                #     "/periosonic-multi-fluid-irrigator#product-detail-tab",
                #     "quantity": 3,
                # },
                {
                    "product_id": "4556-394",
                    "product_url": "https://shop.benco.com/Product/2452-311"
                    "/periosonic-multi-fluid-irrigator#product-detail-tab",
                    "quantity": 1,
                },
            ],
        },
        "amazon": {
            "username": os.getenv("AMAZON_USERNAME"),
            "password": os.getenv("AMAZON_PASSWORD"),
            "products": [
                {
                    "product_id": "",
                    "product_url": "",
                    "quantity": 1,
                },
            ],
        },
        SupportedVendor.ImplantDirect: {
            "username": os.getenv("IMPLANT_DIRECT_USERNAME"),
            "password": os.getenv("IMPLANT_DIRECT_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://store.implantdirect.com/us/en/customer/order/print/id/0041532869/",
                "order_id": "1641753",
            },
            "cart_products": [
                CartProduct(
                    product_id="DAP",
                    product_unit="",
                    product_url="https://store.implantdirect.com/dap.html",
                    quantity=1,
                    price=23.12,
                )
            ],
        },
        SupportedVendor.EdgeEndo: {
            "username": os.getenv("EDGE_ENDO_USERNAME"),
            "password": os.getenv("EDGE_ENDO_PASSWORD"),
            "invoice_data": {
                "invoice": "https://store.edgeendo.com/accountinvoice.aspx?RowID=634931",
                "order_id": "634931",
            },
        },
        SupportedVendor.DentalCity: {
            "username": os.getenv("DENTAL_CITY_USERNAME"),
            "password": os.getenv("DENTAL_CITY_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.dentalcity.com/profile/invoicedetails?invoiceid=99533480",
            },
        },
        SupportedVendor.DcDental: {
            "username": os.getenv("DC_DENTAL_USERNAME"),
            "password": os.getenv("DC_DENTAL_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.dcdental.com/app/accounting/print/hotprint.nl"
                "?regular=T&sethotprinter=T&printtype=transaction&trantype=salesord&label=Sales%20Order&id=71396563",
            },
        },
        SupportedVendor.CrazyDental: {
            "username": os.getenv("CRAZY_DENTAL_USERNAME"),
            "password": os.getenv("CRAZY_DENTAL_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.crazydentalprices.com/app/accounting/print/hotprint.nl"
                "?regular=T&sethotprinter=T&printtype=transaction&trantype=salesord&label=Sales%20Order&id=72444003",
            },
        },
        SupportedVendor.Pearson: {
            "username": os.getenv("PEARSON_USERNAME"),
            "password": os.getenv("PEARSON_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.pearsondental.com/order/c-dtllst.asp?no=979494",
            },
        },
        SupportedVendor.Safco: {
            "username": os.getenv("SAFCO_USERNAME"),
            "password": os.getenv("SAFCO_PASSWORD"),
            "invoice_data": {
                "invoice_link": "https://www.safcodental.com/my-account/invoices/1838206.pdf",
            },
        },
    }


class ScraperTestCase(IntEnum):
    TEST_LOGIN = auto()
    TEST_CLEAR_CART = auto()
    TEST_DOWNLOAD_INVOICE = auto()
    TEST_DOWNLOAD_INVOICE_WITH_FAKE = auto()
    TEST_GET_ORDERS = auto()
    TEST_CONFIRM_ORDER = auto()
    TEST_MAKE_INVOICE_TEMPLATE = auto()
    TEST_GET_ACCOUNT_ID = auto()


async def test_scraper(test: ScraperTestCase, vendors):
    from apps.scrapers.scraper_factory import ScraperFactory

    testing_data = get_testing_data()
    tasks = []
    async with ClientSession(timeout=ClientTimeout(30)) as session:
        async for vendor in vendors:
            scraper_testing_data = testing_data[SupportedVendor(vendor.slug)]
            scraper = ScraperFactory.create_scraper(
                vendor=vendor,
                session=session,
                username=scraper_testing_data["username"],
                password=scraper_testing_data["password"],
            )
            if test == ScraperTestCase.TEST_LOGIN:
                tasks.append(scraper.login())
            else:
                if test == ScraperTestCase.TEST_CLEAR_CART:
                    tasks.append(scraper.clear_cart())
                elif test == ScraperTestCase.TEST_DOWNLOAD_INVOICE:
                    tasks.append(scraper.download_invoice(**scraper_testing_data["invoice_data"]))
                elif test == ScraperTestCase.TEST_GET_ORDERS:
                    tasks.append(scraper.get_orders(perform_login=True))
                elif test == ScraperTestCase.TEST_CONFIRM_ORDER:
                    tasks.append(scraper.confirm_order(scraper_testing_data["cart_products"]))
                elif test == ScraperTestCase.TEST_MAKE_INVOICE_TEMPLATE:
                    invoice_info = InvoiceInfoFactory()
                    tasks.append(scraper.make_invoice_template(invoice_info))
                elif test == ScraperTestCase.TEST_DOWNLOAD_INVOICE_WITH_FAKE:
                    invoice_info = InvoiceInfoFactory()
                    invoice_content = await scraper.make_invoice_template(invoice_info)
                    tasks.append(scraper.html2pdf(invoice_content))
                elif test == ScraperTestCase.TEST_GET_ACCOUNT_ID:
                    tasks.append(scraper.get_account_id())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        if test in [ScraperTestCase.TEST_DOWNLOAD_INVOICE, ScraperTestCase.TEST_DOWNLOAD_INVOICE_WITH_FAKE]:
            for vendor, result in zip(vendors, results):
                if not isinstance(result, bytes):
                    continue
                with open(f"{vendor.slug}.pdf", "wb") as f:
                    f.write(result)
        else:
            print(results)


if __name__ == "__main__":
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from dotenv import load_dotenv

    load_dotenv()

    from apps.accounts.models import Vendor

    testing_scrapers = [
        SupportedVendor.Net32,
        SupportedVendor.UltraDent,
        # SupportedVendor.Benco,
        # SupportedVendor.Darby,
        SupportedVendor.DentalCity,
        # SupportedVendor.ImplantDirect,
        SupportedVendor.EdgeEndo,
        # SupportedVendor.Patterson,
        # SupportedVendor.DcDental,
        # SupportedVendor.CrazyDental,
        # SupportedVendor.Pearson,
        # SupportedVendor.Safco,
        # SupportedVendor.HenrySchein,
    ]
    vendors = Vendor.objects.filter(slug__in=[scraper.value for scraper in testing_scrapers])
    asyncio.run(test_scraper(ScraperTestCase.TEST_DOWNLOAD_INVOICE, vendors))
