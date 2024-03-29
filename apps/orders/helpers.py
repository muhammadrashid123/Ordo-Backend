import asyncio as aio
import csv
import datetime
import itertools
import logging
import traceback
from collections import defaultdict
from decimal import Decimal
from functools import reduce
from itertools import chain
from operator import or_
from typing import Dict, Iterator, List, Optional, TypedDict, Union

import pandas as pd
import requests
from aiohttp import ClientSession, ClientTimeout
from asgiref.sync import sync_to_async
from dateutil import rrule
from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchVectorField
from django.db.models import (
    BooleanField,
    Case,
    Count,
    DecimalField,
    Exists,
    F,
    Model,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.expressions import ExpressionWrapper, Func, RawSQL
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from slugify import slugify

from apps.accounts.models import Office as OfficeModel
from apps.accounts.models import OfficeVendor as OfficeVendorModel
from apps.accounts.models import Vendor as VendorModel
from apps.api_clients.factory import APIClientFactory
from apps.common import messages as msgs
from apps.common.choices import OrderStatus, OrderType, ProductStatus
from apps.common.query import Replacer
from apps.common.tracing.decorators import inject_session
from apps.common.tracing.har_uploader import (
    upload_and_notify_order_fetch_session,
    upload_and_notify_vendor_order_session,
    upload_traced_session,
)
from apps.common.tracing.traced_session import TracedSession
from apps.common.utils import (
    batched,
    bulk_create,
    bulk_update,
    concatenate_list_as_string,
    concatenate_strings,
    convert_string_to_price,
    find_numeric_values_from_string,
    find_words_from_string,
    get_file_name_and_ext,
    remove_dash_between_numerics,
    sort_and_write_to_csv,
)
from apps.orders.models import OfficeProduct as OfficeProductModel
from apps.orders.models import OfficeProductCategory as OfficeProductCategoryModel
from apps.orders.models import Order as OrderModel
from apps.orders.models import Procedure as ProcedureModel
from apps.orders.models import ProcedureCode as ProcedureCodeModel
from apps.orders.models import Product as ProductModel
from apps.orders.models import ProductCategory as ProductCategoryModel
from apps.orders.models import ProductImage as ProductImageModel
from apps.orders.models import VendorOrder as VendorOrderModel
from apps.orders.models import VendorOrderProduct as VendorOrderProductModel
from apps.scrapers.errors import VendorAuthenticationFailed as VendorAuthFailed
from apps.scrapers.scraper_factory import ScraperFactory
from apps.slack.bot import notify
from apps.types.orders import CartProduct
from apps.vendor_clients.async_clients import BaseClient as BaseAsyncClient
from apps.vendor_clients.sync_clients import BaseClient as BaseSyncClient
from apps.vendor_clients.types import Product, ProductPrice, VendorCredential
from config.constants import API_AVAILABLE_VENDORS, FORMULA_VENDORS, NON_FORMULA_VENDORS
from config.utils import get_client_session
from services.opendental import OpenDentalClient

SmartID = Union[int, str]
ProductID = SmartID
ProductIDs = List[ProductID]
CSV_DELIMITER = "!@#$%"

logger = logging.getLogger(__name__)


class ParentProduct(TypedDict):
    product: ProductModel
    children_ids: ProductIDs


class OfficeProductHelper:
    @staticmethod
    def get_available_sibling_products(office: Union[SmartID, OfficeModel], product: Union[SmartID, ProductModel]):
        if isinstance(product, str):
            product = ProductModel.objects.get(id=product)
        if isinstance(office, OfficeModel):
            office_id = office.id
        else:
            office_id = office

        office_products = OfficeProductModel.objects.filter(Q(office_id=office_id))
        if product.parent:
            sibling_products = (
                product.parent.children.select_related("vendor")
                .prefetch_related(Prefetch("office_products", queryset=office_products, to_attr="office_product"))
                .exclude(id=product.id)
            )
            ret = []
            for product in sibling_products:
                if product.vendor.slug in ("net_32", "implant_direct", "edge_endo", "dental_city"):
                    if product.price is None or product.price == 0:
                        continue
                else:
                    if product.office_product and product.office_product[0].product_vendor_status:
                        pass

                ret.append(product)
            return ret
        return ProductModel.objects.none()

    @staticmethod
    def get_associated_office_product(
        office: Union[SmartID, OfficeModel],
        product: Union[SmartID, ProductModel],
        is_inventory: Optional[bool] = None,
    ) -> Optional[OfficeProductModel]:
        if isinstance(office, OfficeModel):
            office = office.id

        q = Q(product_id=product) & Q(office_id=office)
        if is_inventory is not None:
            q &= Q(is_inventory=is_inventory)

        office_product = OfficeProductModel.objects.filter(q).first()
        if office_product:
            return office_product

    @staticmethod
    def get_product_price(office: OfficeModel, product: ProductModel) -> Optional[Decimal]:
        if product.vendor.slug in NON_FORMULA_VENDORS:
            return product.price

        office_product = OfficeProductModel.objects.filter(product=product, office=office).first()
        if office_product and office_product.price:
            return office_product.price
        return product.price

    @staticmethod
    async def get_office_vendors(office_id: str, vendor_slugs: List[str]) -> Dict[str, VendorCredential]:
        office_vendors = OfficeVendorModel.objects.filter(office_id=office_id, vendor__slug__in=vendor_slugs).values(
            "vendor__slug", "username", "password"
        )
        return {
            office_vendor["vendor__slug"]: {
                "username": office_vendor["username"],
                "password": office_vendor["password"],
            }
            async for office_vendor in office_vendors
        }

    @staticmethod
    async def update_products_prices(products_prices: Dict[str, ProductPrice], office_id: str):
        """Store product prices to table"""
        print("update_products_prices")
        current_time = timezone.localtime()
        product_ids = products_prices.keys()
        products = await ProductModel.objects.select_related("vendor").ain_bulk(product_ids)
        office_products = OfficeProductModel.objects.select_related("product").filter(
            office_id=office_id, product_id__in=product_ids
        )

        updated_product_ids = []
        async for office_product in office_products:
            pprice = products_prices[office_product.product_id]
            if pprice["price"] != 0 and pprice["product_vendor_status"] != "Network Error":
                for k, v in pprice.items():
                    setattr(office_product, k, v)
            office_product.last_price_updated = current_time
            updated_product_ids.append(office_product.product_id)

        if office_products:
            await OfficeProductModel.objects.abulk_update(
                objs=office_products, fields=["price", "product_vendor_status", "last_price_updated"], batch_size=500
            )

        # update product title
        t_products = ProductModel.objects.filter(pk__in=product_ids)
        products_title_to_be_updated = []
        async for tp in t_products:
            if tp.id in products_prices:
                tp.name = (
                    products_prices[tp.id]["name"]
                    if tp.id in products_prices and "name" in products_prices[tp.id]
                    else tp.name
                )
                products_title_to_be_updated.append(tp)
        await ProductModel.objects.abulk_update(
            objs=products_title_to_be_updated,
            fields=["name"],
            batch_size=500,
        )

        # update product price
        products_to_be_updated = []
        for product_id, product in products.items():
            if product.vendor.slug not in NON_FORMULA_VENDORS:
                continue
            if (
                products_prices[product_id]["price"] != 0
                and products_prices[product_id]["product_vendor_status"] != "Network Error"
            ):
                product.price = products_prices[product_id]["price"]
                product.product_vendor_status = products_prices[product_id]["product_vendor_status"]
                product.last_price_updated = current_time
                products_to_be_updated.append(product)

        if products_to_be_updated:
            await ProductModel.objects.abulk_update(
                objs=products_to_be_updated,
                fields=["name", "price", "product_vendor_status", "last_price_updated"],
                batch_size=500,
            )

        creating_products = []
        for product_id in product_ids:
            if product_id in updated_product_ids:
                continue
            creating_products.append(
                OfficeProductModel(
                    office_id=office_id,
                    product=products[product_id],
                    price=products_prices[product_id]["price"],
                    last_price_updated=current_time,
                    product_vendor_status=products_prices[product_id]["product_vendor_status"],
                )
            )

        await OfficeProductModel.objects.abulk_create(creating_products, batch_size=500)

    @staticmethod
    async def get_product_prices_by_ids(
        product_ids: List[str], office: Union[SmartID, OfficeModel]
    ) -> Dict[str, ProductPrice]:
        products: dict[int, ProductModel] = await ProductModel.objects.select_related("vendor", "category").ain_bulk(
            product_ids
        )
        return await OfficeProductHelper.get_product_prices(products, office)

    @staticmethod
    async def update_product_prices(
        products: Dict[SmartID, ProductModel], office: Union[SmartID, OfficeModel], from_api: bool = False
    ) -> Dict[str, ProductPrice]:
        """
        This return prices for products
        1. fetch prices from database
        2. for products whose prices do not exist, we try to fetch prices from vendors
        """
        # TODO: add more error handling
        if isinstance(office, OfficeModel):
            office_id = office.id
        else:
            office_id = office

        product_prices_from_db = await OfficeProductHelper.get_products_prices_from_db(products, office_id)
        print("product_prices_from_db", product_prices_from_db)
        # product_prices_from_db[914176]['price'] = None
        # product_prices_from_db[914176]['product_vendor_status'] = None

        products_to_be_fetched = {}

        for product_id, product in products.items():
            products_to_be_fetched[product_id] = product.to_dict(include_images=False)

        print(f"==== Number of products to fetch from their sites: {len(products_to_be_fetched)} ====")
        if not from_api and products_to_be_fetched:
            product_prices_from_vendors = await OfficeProductHelper.get_product_prices_from_vendors(
                products_to_be_fetched, office_id
            )

            print("==== fetching prices from the online site ====")
            print(product_prices_from_vendors)
            print(" ================= done fetching ============")

            return {**product_prices_from_db, **product_prices_from_vendors}

        return product_prices_from_db

    @staticmethod
    async def get_product_prices(
        products: Dict[SmartID, ProductModel], office: Union[SmartID, OfficeModel], from_api: bool = False
    ) -> Dict[str, ProductPrice]:
        """
        This return prices for products
        1. fetch prices from database
        2. for products whose prices do not exist, we try to fetch prices from vendors
        """
        # TODO: add more error handling
        if isinstance(office, OfficeModel):
            office_id = office.id
        else:
            office_id = office

        product_prices_from_db = await OfficeProductHelper.get_products_prices_from_db(products, office_id)
        products_to_be_fetched = {}

        for product_id, product in products.items():
            products_to_be_fetched[product_id] = product.to_dict(include_images=False)

        print(f"==== Number of products to fetch from their sites: {len(products_to_be_fetched)} ====")
        if not from_api and products_to_be_fetched:
            product_prices_from_vendors = await OfficeProductHelper.get_product_prices_from_vendors(
                products_to_be_fetched, office_id
            )

            print("==== fetching prices from the online site ====")
            print(product_prices_from_vendors)
            print(" ================= done fetching ============")

            return {**product_prices_from_db, **product_prices_from_vendors}

        return product_prices_from_db

    # @staticmethod
    # async def update_crazy_dental_products_prices(office_id, product_id):
    #     get_vendor_customer_id_async = sync_to_async(get_vendor_customer_id)
    #     customer_id = await get_vendor_customer_id_async(office_id=office_id)
    #
    #     print("customer_id========", customer_id)
    #     print("customer_id", product_id)
    #     headers = {"Content-Type": "application/json"}
    #     params = {
    #         "script": "customscript_pri_rest_product",
    #         "deploy": "customdeploy_pri_rest_product_ordo4837",
    #         "itemid": product_id,
    #         "customerid": customer_id,
    #     }
    #     response = requests.get(url=crazy_dental_Base_url, params=params, headers=headers, auth=oauth)
    #     print("response", response.json())
    #     if response.status_code == 200:
    #         json_response = response.json()
    #         if json_response["success"]:
    #             data = json_response["result"]
    #             product_price = float(data[0]["pricing_unitprice"])
    #
    #             return product_price

    @staticmethod
    async def get_products_prices_from_db(
        products: Dict[str, ProductModel], office_id: str
    ) -> Dict[str, ProductPrice]:
        product_ids_from_formula_vendors = []
        product_ids_from_non_formula_vendors = []
        for product_id, product in products.items():
            if product.vendor.slug in FORMULA_VENDORS:
                product_ids_from_formula_vendors.append(product_id)
            else:
                product_ids_from_non_formula_vendors.append(product_id)

        product_prices = defaultdict(dict)

        # Get prices of products from formula vendors
        office_products = OfficeProductModel.objects.filter(
            product_id__in=product_ids_from_formula_vendors, office_id=office_id
        ).values("product_id", "price", "product_vendor_status")

        async for office_product in office_products:
            product_prices[office_product["product_id"]]["price"] = office_product["price"]
            product_prices[office_product["product_id"]]["product_vendor_status"] = office_product[
                "product_vendor_status"
            ]

        # Get prices of products from non-formula vendors
        for product_id in product_ids_from_non_formula_vendors:
            vendor_obj = ProductModel.objects.select_related("vendor").get(id=product_id)
            if vendor_obj and vendor_obj.vendor.slug == "crazy_dental":
                product_prices[product_id]["price"] = vendor_obj.price
                product_prices[product_id]["product_vendor_status"] = ""

            else:
                recent_price = products[product_id].recent_price
                if recent_price:
                    product_prices[product_id]["price"] = recent_price
                    product_prices[product_id]["product_vendor_status"] = ""

        return product_prices

    @staticmethod
    async def get_product_prices_from_vendors(products: Dict[str, Product], office_id: str) -> Dict[str, ProductPrice]:
        print("get_product_prices_from_vendors")
        if not products:
            return {}
        vendor_slugs = list(set([product["vendor"] for product_id, product in products.items()]))
        vendors_credentials = await OfficeProductHelper.get_office_vendors(
            vendor_slugs=vendor_slugs, office_id=office_id
        )
        product_prices_from_vendors = await VendorHelper.get_products_prices(
            products=products, vendors_credentials=vendors_credentials, use_async_client=True, office_id=office_id
        )
        await OfficeProductHelper.update_products_prices(product_prices_from_vendors, office_id)

        return product_prices_from_vendors

    @staticmethod
    def get_vendor_product_ids(office_id: str, vendor_slug: str):
        # TODO: let's remove annotations if we are not using them?
        # office_products = OfficeProductModel.objects.filter(Q(office_id=office_id) & Q(product_id=OuterRef("pk")))
        return (
            ProductModel.objects
            # .annotate(office_product_price=Subquery(office_products.values("price")[:1]))
            # .annotate(
            #     product_price=Case(
            #         When(office_product_price__isnull=False, then=F("office_product_price")),
            #         When(price__isnull=False, then=F("price")),
            #         default=Value(None),
            #     )
            # )
            # .filter(vendor__slug=vendor_slug,  product_price__isnull=True)
            .filter(vendor__slug=vendor_slug).values_list("id", flat=True)
        )

    @staticmethod
    async def get_all_product_prices_from_vendors(
        office_id: str, vendor_slugs: List[str], batch_size=20, sleep_time=1
    ):
        for vendor_slug in vendor_slugs:
            vendor_product_ids: List[int] = [
                product_id async for product_id in OfficeProductHelper.get_vendor_product_ids(office_id, vendor_slug)
            ]
            print(f"Number of products to update price: {len(vendor_product_ids)}")

            for v_ids in batched(vendor_product_ids, batch_size):
                await OfficeProductHelper.get_product_prices_by_ids(v_ids, office_id)
                await aio.sleep(sleep_time)

        print("======== DONE fetch =========")

    @staticmethod
    async def get_products_from_vendors(
        vendor_slugs: List[str], q: str, min_price: int = 0, max_price: int = 0, office_id: Optional[str] = None
    ):
        pass
        # if office_id:
        #     vendors_credentials = await sync_to_async(OfficeProductHelper.get_office_vendors)(
        #         vendor_slugs=vendor_slugs, office_id=office_id
        #     )
        # product_prices_from_vendors = await VendorHelper.search_products(
        #     vendors_credentials, query: str, page: int = 1, min_price: int = 0, max_price: int = 0, sort_by="price")


class VendorHelper:
    CONSUMER_NUMBERS = 5

    @staticmethod
    async def validate_user_credential(
        vendor_slug: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        try:
            session = await get_client_session()
            vendor_client = BaseAsyncClient.make_handler(
                vendor_slug=vendor_slug,
                session=session,
                username=username,
                password=password,
            )
            await vendor_client.login()
            return True
        except VendorAuthFailed:
            return False

    @staticmethod
    def get_vendor_async_clients(
        vendors_credentials: Dict[str, VendorCredential], session: ClientSession
    ) -> Dict[str, BaseAsyncClient]:
        clients = {}
        for vendor_slug, vendors_credential in vendors_credentials.items():
            clients[vendor_slug] = BaseAsyncClient.make_handler(
                vendor_slug=vendor_slug,
                session=session,
                username=vendors_credential["username"],
                password=vendors_credential["password"],
            )
        return clients

    @staticmethod
    def get_vendor_sync_clients(vendors_credentials: Dict[str, VendorCredential]) -> Dict[str, BaseAsyncClient]:
        clients = {}
        for vendor_slug, vendors_credential in vendors_credentials.items():
            clients[vendor_slug] = BaseSyncClient.make_handler(
                vendor_slug=vendor_slug,
                username=vendors_credential["username"],
                password=vendors_credential["password"],
            )
        return clients

    @staticmethod
    async def get_products_prices(
        products: Dict[str, Product],
        vendors_credentials: Dict[str, VendorCredential],
        use_async_client=True,
        office_id=None,
    ) -> Dict[str, ProductPrice]:
        vendor_products_2_products_mapping = defaultdict(dict)
        vendor_slugs = set()
        for product_id, product in products.items():
            vendor_slugs.add(product["vendor"])
            vendor_products_2_products_mapping[product["vendor"]][product["product_id"]] = product_id

        tasks = []
        if use_async_client:
            aio_session = await get_client_session()
            clients = VendorHelper.get_vendor_async_clients(vendors_credentials, aio_session)
        else:
            clients = VendorHelper.get_vendor_sync_clients(vendors_credentials)
        for vendor_slug in vendor_slugs:
            vendor_products = list(filter(lambda x: x["vendor"] == vendor_slug, products.values()))
            if vendor_slug in clients:
                tasks.append(clients[vendor_slug].get_products_prices(vendor_products, office_id))
        prices_results = await aio.gather(*tasks, return_exceptions=True)

        ret: Dict[str, ProductPrice] = {}
        for vendor_slug, prices_result in zip(vendor_slugs, prices_results):
            if not isinstance(prices_result, dict):
                continue
            for vendor_product_id, price in prices_result.items():
                ret[vendor_products_2_products_mapping[vendor_slug][vendor_product_id]] = price

        if use_async_client:
            if aio_session is not None:
                await aio_session.close()
        return ret

    @staticmethod
    async def search_products(
        vendors_credentials: Dict[str, VendorCredential],
        query: str,
        page: int = 0,
        min_price: int = 0,
        max_price: int = 0,
    ):
        clients = VendorHelper.get_vendor_async_clients(vendors_credentials)
        tasks = []
        for client in clients:
            if hasattr(client, "search_products"):
                tasks.append(client.search_products(query=query, page=page, min_price=min_price, max_price=max_price))

        if tasks:
            search_results = await aio.gather(*tasks, return_exceptions=True)

        return search_results


class ProductHelper:
    @staticmethod
    def get_vendor_category_mapping() -> Dict[str, Dict[str, ProductCategoryModel]]:
        """Return the vendor category vs our product category mapping
        {
            "vendor slug": {
                "vendor category": "our product category",
            }
        }
        Example:
        {
            "henry_schein": {
                "anesthetics": "anesthetics",
            }
        }
        """
        ret = defaultdict(dict)
        product_categories = ProductCategoryModel.objects.all()
        for product_category in product_categories:
            if product_category.vendor_categories is None:
                ret["other"] = product_category
                continue

            for vendor_slug, vendor_categories in product_category.vendor_categories.items():
                for vendor_category in vendor_categories:
                    ret[vendor_slug][vendor_category] = product_category

        return ret

    @staticmethod
    def read_products_from_csv(file_path, output_duplicates: bool = True) -> pd.DataFrame:
        df = pd.read_csv(file_path, na_filter=False, low_memory=False, dtype=str)
        duplicated_products = df[df["product_id"].duplicated()]
        file_name, ext = get_file_name_and_ext(file_path)
        if output_duplicates:
            sort_and_write_to_csv(duplicated_products, columns=["category"], file_name=f"{file_name}_duplicated.csv")
        return df.drop_duplicates(subset=["product_id"], keep="first")

    @staticmethod
    def read_products_from_csv_v2(
        file_path, output_duplicates: bool = True, product_id_field="product_id"
    ) -> Iterator[dict]:
        seen_product_ids = set()
        with open(file_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                row: dict
                product_id = row.get(product_id_field)
                row["product_id"] = product_id
                if product_id in seen_product_ids:
                    continue
                seen_product_ids.add(product_id)
                yield row

    @staticmethod
    def import_products_from_csv_v2(
        file_path, vendor_slug, fields: Optional[List[str]] = None, verbose: bool = True, product_id_field="product_id"
    ):
        csv_products = ProductHelper.read_products_from_csv_v2(
            file_path, output_duplicates=verbose, product_id_field=product_id_field
        )
        vendor = VendorModel.objects.get(slug=vendor_slug)
        category_mapping = ProductHelper.get_vendor_category_mapping()

        # sub_df = df[df_index: df_index + batch_size]
        product_objs_to_be_created = []
        product_objs_to_be_updated = []
        parents_to_create = []
        product_image_urls = []
        for row in csv_products:
            category = row.get("category", "")
            category = slugify(category)
            product_category = category_mapping[vendor_slug].get(category)
            if product_category is None:
                product_category = category_mapping["other"]

            try:
                product_price = convert_string_to_price(row["price"])
            except:  # noqa
                # Ignore the price parsing error and continue...
                product_price = None

            manufacturer_number_origin = row.get("mfg_number")
            manufacturer_number = manufacturer_number_origin.replace("-", "") if manufacturer_number_origin else ""
            product = ProductModel.objects.filter(product_id=row["product_id"], vendor=vendor).first()

            if product:
                if not fields:
                    # Product exists but nothing to update, then skip the product...
                    continue

                for field in fields:
                    if field == "price":
                        value = product_price
                    elif field == "manufacturer_number":
                        value = manufacturer_number
                    elif field == "manufacturer_number_origin":
                        value = manufacturer_number_origin
                    elif field == "category":
                        value = product_category
                    else:
                        value = row[field]

                    # if getattr(product, field) != value:
                    setattr(product, field, value)

                product_objs_to_be_updated.append(product)
            else:
                print(f"Cannot find out {row['product_id']}, so creating the product")
                name = row["name"][:512]
                parents_to_create.append(ProductModel(name=name))
                product_objs_to_be_created.append(
                    {
                        "vendor": vendor,
                        "product_id": row["product_id"],
                        "name": name,
                        "product_unit": row["product_unit"],
                        "url": row["url"],
                        "sku": row["sku"],
                        "category": product_category,
                        "price": product_price,
                        "manufacturer_number": manufacturer_number,
                        "manufacturer_number_origin": manufacturer_number_origin,
                    }
                )
                product_images = row["images"].split(";")
                product_image_urls.append(product_images)

        if product_objs_to_be_updated:
            bulk_update(model_class=ProductModel, objs=product_objs_to_be_updated, fields=fields)
            print(f"{vendor}: {len(product_objs_to_be_updated)} products updated")

        product_images_to_create = []
        if parents_to_create:
            parents = ProductModel.objects.bulk_create(parents_to_create)
            products_to_create = [
                ProductModel(**product_dict, parent=parent)
                for parent, product_dict in zip(parents, product_objs_to_be_created)
            ]
            product_objs = ProductModel.objects.bulk_create(products_to_create)
            print(f"{vendor}: {len(product_objs_to_be_created)} products created")
            for product, product_images in zip(product_objs, product_image_urls):
                for product_image in product_images:
                    product_images_to_create.append(ProductImageModel(product=product, image=product_image))

        bulk_create(model_class=ProductImageModel, objs=product_images_to_create)

    @staticmethod
    def import_products_from_csv(file_path, vendor_slug, fields: Optional[List[str]] = None, verbose: bool = True):
        df = ProductHelper.read_products_from_csv(file_path, output_duplicates=verbose)
        df_index = 0
        batch_size = 500
        df_len = len(df)

        vendor = VendorModel.objects.get(slug=vendor_slug)
        category_mapping = ProductHelper.get_vendor_category_mapping()

        while df_len > df_index:
            sub_df = df[df_index : df_index + batch_size]
            product_objs_to_be_created = []
            product_objs_to_be_updated = []
            for index, row in sub_df.iterrows():
                category = row.get("category", "")
                category = slugify(category)
                product_category = category_mapping[vendor_slug].get(category)
                if product_category is None:
                    product_category = category_mapping["other"]

                try:
                    product_price = convert_string_to_price(row["price"])
                except:  # noqa
                    # Ignore the price parsing error and continue...
                    product_price = None

                manufacturer_number_origin = row.get("mfg_number")
                manufacturer_number = manufacturer_number_origin.replace("-", "") if manufacturer_number_origin else ""
                product = ProductModel.objects.filter(product_id=row["product_id"], vendor=vendor).first()

                if product:
                    if not fields:
                        # Product exists but nothing to update, then skip the product...
                        continue

                    for field in fields:
                        if field == "price":
                            value = product_price
                        elif field == "manufacturer_number":
                            value = manufacturer_number
                        elif field == "manufacturer_number_origin":
                            value = manufacturer_number_origin
                        else:
                            value = row[field]

                        if getattr(product, field) != value:
                            setattr(product, field, value)
                    product_objs_to_be_updated.append(product)
                else:
                    print(f"Cannot find out {row['product_id']}, so creating the product")
                    product_objs_to_be_created.append(
                        ProductModel(
                            vendor=vendor,
                            product_id=row["product_id"],
                            name=row["name"][:512],
                            product_unit=row["product_unit"],
                            url=row["url"],
                            sku=row["sku"],
                            category=product_category,
                            price=product_price,
                            manufacturer_number=manufacturer_number,
                            manufacturer_number_origin=manufacturer_number_origin,
                        )
                    )

            if product_objs_to_be_updated:
                bulk_update(model_class=ProductModel, objs=product_objs_to_be_updated, fields=fields)
                print(f"{vendor}: {len(product_objs_to_be_updated)} products updated")

            if product_objs_to_be_created:
                product_objs = bulk_create(model_class=ProductModel, objs=product_objs_to_be_created)
                print(f"{vendor}: {len(product_objs_to_be_created)} products created")
                product_image_objs = []
                for product, product_images in zip(product_objs, sub_df["images"]):
                    product_images = product_images.split(";")
                    for product_image in product_images:
                        product_image_objs.append(ProductImageModel(product=product, image=product_image))

                bulk_create(model_class=ProductImageModel, objs=product_image_objs)
            df_index += batch_size

    @staticmethod
    def import_promotion_products_from_list(items: List[dict], vendor_slug: str):
        vendor = VendorModel.objects.get(slug=vendor_slug)

        # Remove old promotion fields
        ProductModel.objects.filter(vendor=vendor).update(is_special_offer=False)

        product_objs = []
        for row in items:
            product = ProductModel.objects.filter(product_id=row["product_id"], vendor=vendor).first()
            if product:
                product.is_special_offer = True
                price = convert_string_to_price(row.get("price"))
                if price:
                    product.special_price = price
                if vendor_slug == "patterson":
                    product.promotion_description = row["promo"] or row["FreeGood"]
                else:
                    product.promotion_description = row["promo"]
                product_objs.append(product)
            else:
                print(f"Missing product {row['product_id']}")

        bulk_update(
            model_class=ProductModel,
            objs=product_objs,
            fields=["is_special_offer", "special_price", "promotion_description"],
        )
        print(f"Updated {len(product_objs)}s products")

    @staticmethod
    def import_promotion_products_from_csv(file_path: str, vendor_slug: str):
        df = ProductHelper.read_products_from_csv(file_path, output_duplicates=False)
        df_index = 0
        batch_size = 500
        df_len = len(df)

        vendor = VendorModel.objects.get(slug=vendor_slug)

        # Remove old promotion fields
        ProductModel.objects.filter(vendor=vendor).update(is_special_offer=False)

        while df_len > df_index:
            sub_df = df[df_index : df_index + batch_size]
            product_objs = []
            for index, row in sub_df.iterrows():
                product = ProductModel.objects.filter(product_id=row["product_id"], vendor=vendor).first()
                if product:
                    product.is_special_offer = True
                    price = convert_string_to_price(row.get("price"))
                    if price:
                        product.special_price = price
                    if vendor_slug == "patterson":
                        product.promotion_description = row["promo"] or row["FreeGood"]
                    else:
                        product.promotion_description = row["promo"]
                    product_objs.append(product)
                else:
                    print(f"Missing product {row['product_id']}")

            bulk_update(
                model_class=ProductModel,
                objs=product_objs,
                fields=["is_special_offer", "special_price", "promotion_description"],
            )
            print(f"Updated {len(product_objs)}s products")
            df_index += batch_size

    @staticmethod
    def group_products_by_manufacturer_numbers(since: Optional[datetime.datetime] = None, vendor_id=-1):
        """group products by using manufacturer_number. this number is identical for products"""
        products = ProductModel.objects.filter(manufacturer_number__isnull=False)
        if since:
            products = products.filter(updated_at__gt=since)
        if vendor_id != -1:
            products = products.filter(vendor_id=vendor_id)
        manufacturer_numbers = set(
            products.order_by("manufacturer_number")
            .values("manufacturer_number")
            .annotate(products_count=Count("vendor"))
            .values_list("manufacturer_number", flat=True)
        )
        products_to_be_updated = []
        # parent_products_to_be_created = []
        for i, manufacturer_number in enumerate(manufacturer_numbers):
            if len(manufacturer_number) < 1:
                continue
            print(f"Calculating {i}th: {manufacturer_number}")
            similar_products = ProductModel.objects.filter(
                manufacturer_number=manufacturer_number, vendor__isnull=False
            )

            # remove already existing parent products
            similar_product_ids = similar_products.values_list("id", flat=True)
            parent_products = ProductModel.objects.filter(child__id__in=similar_product_ids).distinct()
            product_names = sorted(list(similar_products.values_list("name", flat=True)), key=lambda x: len(x))
            display_text = concatenate_list_as_string(similar_product_ids, delimiter=",")

            parent_products_count = parent_products.count()
            if parent_products_count == 1:
                parent_product = parent_products.first()
                print(f"Parent product already existed {parent_product.id} {parent_product.name}: {display_text}")
                parent_product.manufacturer_number = manufacturer_number
                parent_product.save()
            else:
                if parent_products_count >= 2:
                    parent_product_ids = parent_products.values_list("id", flat=True)
                    display_text = f"{concatenate_list_as_string(parent_product_ids, delimiter=',')}: {display_text}"
                    print(f"Existed 2 parents {display_text}")
                    ProductModel.objects.filter(id__in=parent_product_ids).delete()

                parent_product = ProductModel.objects.create(
                    name=product_names[0], manufacturer_number=manufacturer_number
                )

            for product in similar_products:
                product.parent = parent_product
                products_to_be_updated.append(product)

                # parent_products_to_be_created.append(
                #     ParentProduct(
                #         product=ProductModel(name=product_names[0], manufacturer_number=manufacturer_number),
                #         children_ids=similar_product_ids,
                #     )
                # )

        print("updating databases...")
        bulk_update(model_class=ProductModel, objs=products_to_be_updated, fields=["parent"])
        # ProductHelper.create_parent_products(parent_products_to_be_created)

    @staticmethod
    def group_products(
        product_ids: Optional[ProductID] = None,
        include_category_slugs: Optional[List[str]] = None,
        exclude_category_slugs: Optional[List[str]] = None,
        commit: bool = True,
    ):
        """Group products"""
        products = ProductModel.objects.all()
        if product_ids:
            products = products.filter(id__in=product_ids)

        vendor_slugs = products.order_by("vendor").values_list("vendor__slug", flat=True).distinct()
        if len(vendor_slugs) <= 1:
            # if the products are from one vendor, don't need to proceed further
            return None

        # get the list of similar product ids by product category
        product_categories = ProductCategoryModel.objects.order_by("name")
        if include_category_slugs:
            product_categories = product_categories.filter(slug__in=include_category_slugs)

        if exclude_category_slugs:
            product_categories = product_categories.exclude(slug__in=exclude_category_slugs)

        for product_category in product_categories:
            # In the future, we shouldn't perform group again for already grouped products,
            # but for now, we can perform this operation for all products
            ProductModel.objects.filter(vendor__isnull=True, category=product_category).delete()

            print(f"calculating {product_category.name}")
            ProductHelper.group_products_by_category(products, product_category, commit)

    @staticmethod
    def group_products_by_category(
        products: QuerySet, product_category: Optional[ProductCategoryModel] = None, commit: bool = True
    ) -> List[ProductIDs]:
        """
        Return the list of a group of product ids.
        Each element from the list is a list of product id, those products are very similar
        """
        if product_category is None or product_category.slug.lower() == "other":
            vendor_slugs = products.order_by("vendor").values_list("vendor__slug", flat=True).distinct()
        else:
            vendor_slugs = product_category.vendor_categories.keys()
            if len(vendor_slugs) <= 1:
                return []

        vendors_products = {}
        product_ids_by_vendors = []
        for vendor_slug in vendor_slugs:
            vendor_products = products.filter(vendor__slug=vendor_slug).values("id", "vendor", "name")
            if product_category:
                vendor_products = vendor_products.filter(category=product_category)

            for vendor_product in vendor_products:
                vendors_products[vendor_product["id"]] = {
                    "vendor": vendor_product["vendor"],
                    "name": vendor_product["name"],
                }

            if vendor_products:
                product_ids_by_vendors.append(vendor_products.values_list("id", flat=True))

        if len(product_ids_by_vendors) <= 1:
            return []

        similar_product_ids_list: List[ProductIDs] = ProductHelper.group_products_by_name(
            vendors_products, product_ids_by_vendors
        )
        parent_product_objs: List[ParentProduct] = []

        print("updating database")
        if commit:
            for similar_product_ids in similar_product_ids_list:
                similar_products = products.filter(id__in=similar_product_ids)
                parent_products = similar_products.filter(child__isnull=False)

                if parent_products:
                    # at least one of similar products has already children.
                    # in this case we should add other products as children of that parent product.
                    # If there are more than multiple parents, we should merge them into one

                    parent_product_ids = parent_products.values_list("id", flat=True)
                    parent_product = parent_products.first()
                    existing_children_products = ProductModel.objects.filter(parent_id__in=parent_product_ids)

                    new_similar_products = []
                    similar_products = similar_products.exclude(child__isnull=False)
                    for similar_product in chain.from_iterable([similar_products, existing_children_products]):
                        similar_product.parent = parent_product
                        new_similar_products.append(similar_product)

                    bulk_update(ProductModel, new_similar_products, fields=["parent"])

                    # delete other parents
                    parent_products.exclude(id=parent_product.id).delete()

                else:
                    parent_product_objs.append(
                        ParentProduct(
                            product=ProductModel(
                                name=similar_products[0].name,
                                category=similar_products[0].category,
                            ),
                            children_ids=similar_product_ids,
                        )
                    )

            ProductHelper.create_parent_products(parent_product_objs)

    @staticmethod
    def group_products_by_name(products, product_ids_by_vendors) -> List[ProductIDs]:
        # TODO: This algorith should be updated. like this way
        """
        1. find out 2-length similar products like current one
        2. from the 3-length product comparison, current approach seems bad,
            even though we don't calculate similarity for all pairs
        3. group_by_vendors, run combination, products just like 2-length comparison, that will be faster.
        """
        threshold = 0.7
        n_similarity = 2
        vendors_count = len(product_ids_by_vendors)
        similar_products_candidates = defaultdict(list)

        # find out all 2-length similar products
        products_combinations = itertools.combinations(product_ids_by_vendors, n_similarity)
        for products_combination in products_combinations:
            for product_ids in itertools.product(*products_combination):
                vendor_product_names = [products[product_id]["name"] for product_id in product_ids]
                similarity = ProductHelper.get_similarity(*vendor_product_names)

                if similarity > threshold:
                    display_text = "; ".join(
                        [f'{products[product_id]["vendor"]}-{product_id}' for product_id in product_ids]
                    )
                    print(f"{similarity:.2f}: {display_text}")
                    similar_products_candidates[n_similarity].append([f"{similarity:.2f}", *product_ids])

        # when finding more than 3-length similar products we need to check from candidates pairs
        n_similarity = 3
        while n_similarity <= vendors_count:
            print(f"calculating {n_similarity}=======")
            n_threshold = threshold ** (n_similarity - 1)
            n_1_similarity_products_pairs_length = len(similar_products_candidates[n_similarity - 1])
            if not n_1_similarity_products_pairs_length:
                break

            well_matching_pair_ids = set()
            for i in range(n_1_similarity_products_pairs_length - 1):
                ith_similar_products_pair = similar_products_candidates[n_similarity - 1][i][1:]
                ith_similar_product_ids = set(ith_similar_products_pair)
                ith_similar_product_vendors = set(
                    [products[product_id]["vendor"] for product_id in ith_similar_products_pair]
                )
                print(f"comparing with {i}th element ")
                for j in range(i + 1, n_1_similarity_products_pairs_length):
                    jth_similar_products_pair = similar_products_candidates[n_similarity - 1][j][1:]
                    jth_similar_product_ids = set(jth_similar_products_pair)
                    jth_similar_product_vendors = set(
                        [products[product_id]["vendor"] for product_id in jth_similar_products_pair]
                    )
                    if not ith_similar_product_ids.intersection(jth_similar_product_ids):
                        continue

                    proucts_difference = ith_similar_product_ids - jth_similar_product_ids
                    if len(proucts_difference) > 1:
                        continue

                    ith_vendor_difference = ith_similar_product_vendors - jth_similar_product_vendors
                    jth_vendor_difference = jth_similar_product_vendors - ith_similar_product_vendors

                    if ith_vendor_difference == jth_vendor_difference:
                        continue

                    if tuple(ith_similar_product_ids | jth_similar_product_ids) in well_matching_pair_ids:
                        continue

                    similar_products_pair = ith_similar_product_ids | jth_similar_product_ids
                    well_matching_pair_ids.add(tuple(similar_products_pair))
                    vendor_product_names = [products[product_id]["name"] for product_id in similar_products_pair]
                    similarity = ProductHelper.get_similarity(*vendor_product_names)

                    if similarity > n_threshold:
                        display_text = "; ".join(
                            [f'{products[product_id]["vendor"]}-{product_id}' for product_id in similar_products_pair]
                        )
                        print(f"{similarity:.2f}: {display_text}")
                        similar_products_candidates[n_similarity].append([f"{similarity:.2f}", *similar_products_pair])

            n_similarity += 1

        similar_products_candidates = chain.from_iterable([value for _, value in similar_products_candidates.items()])
        similar_products_list = ProductHelper.clean_well_matching_paris(similar_products_candidates)
        return [similar_products[1:] for similar_products in similar_products_list]

    @staticmethod
    def clean_well_matching_paris(well_matching_pairs):
        """
        This will remove partly-duplicated product paris if the well_matching_paris contains
        [(1, vendorA_productID, vendorB_productID), (0.9, vendorA_productID, vendorB_productID)]
        the second pair is not needed.
        """
        cleaned_well_matching_paris = []
        included_product_ids = set()
        well_matching_pairs = sorted(well_matching_pairs, key=lambda x: (len(x), x[0]), reverse=True)
        for well_matching_pair in well_matching_pairs:
            well_matching_product_pair_ids = set(well_matching_pair[1:])
            if included_product_ids & well_matching_product_pair_ids:
                continue
            included_product_ids |= well_matching_product_pair_ids
            cleaned_well_matching_paris.append(well_matching_pair)
        return cleaned_well_matching_paris

    @staticmethod
    def get_similarity(*products, key=None):
        total_words = set()
        matched_words = set()
        total_numeric_values = set()
        matched_numeric_values = set()
        excluded_words = {"of", "and", "with"}

        for product_i, product in enumerate(products):
            if isinstance(product, dict):
                product_name = product[key]
            elif isinstance(product, Model):
                product_name = getattr(product, key)
            else:
                product_name = product

            product_numeric_values = set(map(str.lower, find_numeric_values_from_string(product_name)))
            product_words = set(map(str.lower, find_words_from_string(product_name)))
            product_words = product_words - product_numeric_values
            product_words -= excluded_words
            total_words.update(product_words)
            total_numeric_values.update(product_numeric_values)
            if product_i == 0:
                matched_words = product_words
                matched_numeric_values = product_numeric_values
            else:
                matched_words &= product_words
                matched_numeric_values &= product_numeric_values

        if len(total_numeric_values):
            percentage = 0.4 * len(matched_words) / len(total_words) + 0.6 * len(matched_numeric_values) / len(
                total_numeric_values
            )
        else:
            percentage = len(matched_words) / len(total_words)
        return percentage

    @staticmethod
    def export_similar_products_to_csv(
        to: str = "output.csv",
        include_category_slugs: Optional[List[str]] = None,
        exclude_category_slugs: Optional[List[str]] = None,
    ):
        """export grouped products to csv format"""
        products = ProductModel.objects.filter(vendor__isnull=True).order_by("category__name")
        if include_category_slugs:
            products = products.filter(category__slug__in=include_category_slugs)

        if exclude_category_slugs:
            products = products.exclude(category__slug__in=exclude_category_slugs)

        # TODO: this might be slower than using pandas
        with open(to, "w") as f:
            csvwriter = csv.writer(f)
            csvwriter.writerow(["category", "product_ids", "vendor_products", "product_names", "product_urls"])
            for product in products:
                children_products = product.children.values("id", "product_id", "vendor__slug", "name", "url")
                product_ids = []
                vendor_products = []
                product_names = []
                product_urls = []
                for children_product in children_products:
                    product_ids.append(f'{children_product["id"]}')
                    vendor_products.append(f'{children_product["vendor__slug"]}-{children_product["product_id"]}')
                    product_names.append(children_product["name"])
                    product_urls.append(children_product["url"])

                csvwriter.writerow(
                    [
                        product.category.slug,
                        concatenate_strings(product_ids, delimeter=CSV_DELIMITER),
                        concatenate_strings(vendor_products, delimeter=CSV_DELIMITER),
                        concatenate_strings(product_names, delimeter=CSV_DELIMITER),
                        concatenate_strings(product_urls, delimeter=CSV_DELIMITER),
                    ]
                )

    @staticmethod
    def import_products_similarity(file_name: str, use_by: str = "id"):
        print(f"reading {file_name}..")
        df = pd.read_csv(file_name)

        parent_product_objs: List[ParentProduct] = []
        product_categories = ProductCategoryModel.objects.all()
        product_categories = {category.slug: category for category in product_categories}
        for _, row in df.iterrows():
            category = product_categories[row["category"]]
            if use_by == "id":
                product_ids = row["product_ids"].split(CSV_DELIMITER)
            else:
                vendor_products = row["vendor_products"].split(CSV_DELIMITER)
                vendor_products = [
                    Q(vendor__slug=vendor_product.split("-")[0]) & Q(product_id=vendor_product.split("-", 1)[1])
                    for vendor_product in vendor_products
                ]
                q = reduce(or_, vendor_products)
                product_ids = list(ProductModel.objects.filter(q).values_list("id", flat=True))

            product_names = row["product_names"].split(CSV_DELIMITER)
            parent_product_objs.append(
                ParentProduct(
                    product=ProductModel(
                        name=product_names[0],
                        category=category,
                    ),
                    children_ids=product_ids,
                )
            )
        print("updating databases..")
        ProductHelper.create_parent_products(parent_product_objs)

    @staticmethod
    def create_parent_products(parent_product_objs: List[ParentProduct]):
        if parent_product_objs:
            parent_products = bulk_create(
                ProductModel, [parent_product_obj["product"] for parent_product_obj in parent_product_objs]
            )
            for parent_product_instance, parent_product_obj in zip(parent_products, parent_product_objs):
                children_products = ProductModel.objects.filter(id__in=parent_product_obj["children_ids"])
                for children_product in children_products:
                    children_product.parent = parent_product_instance
                bulk_update(ProductModel, children_products, fields=["parent"])

    @staticmethod
    def get_products(
        office: Union[OfficeModel, SmartID],
        fetch_parents: bool = True,
        product_ids: Optional[List[SmartID]] = None,
        products: Optional[QuerySet] = None,
        selected_products: Optional[List[SmartID]] = None,
    ):
        """
        fetch_parents:  True:   fetch parent products
                        False:  fetch all products
        selected_products: list of product id, product ids in this list will be ordered first
        """
        if isinstance(office, OfficeModel):
            office_pk = office.id
        else:
            office_pk = office

        # get products from vendors that are linked to the office account
        if products is None:
            products = ProductModel.objects.select_related("vendor", "category")

        connected_vendor_ids = OfficeVendorHelper.get_connected_vendor_ids(office_pk)
        if fetch_parents:
            products = products.filter(parent__isnull=True)

            if product_ids is not None:
                products = products.filter(Q(id__in=product_ids) | Q(child__id__in=product_ids)).distinct()

            products = products.filter(
                Q(vendor_id__in=connected_vendor_ids)
                | (Q(vendor__isnull=True) & Q(child__vendor_id__in=connected_vendor_ids))
            ).distinct()
        else:
            if product_ids is not None:
                products = products.filter(Q(id__in=product_ids))

            products = products.filter(Q(vendor_id__in=connected_vendor_ids))

        if selected_products is None:
            selected_products = []

        # TODO: this should be optimized
        office_products = OfficeProductModel.objects.filter(Q(office_id=office_pk))
        price_least_update_date = timezone.localtime() - datetime.timedelta(days=settings.PRODUCT_PRICE_UPDATE_CYCLE)
        office_product_price = OfficeProductModel.objects.filter(
            Q(office_id=office_pk) & Q(product_id=OuterRef("pk")) & Q(last_price_updated__gte=price_least_update_date)
        ).values("price")

        # we treat parent product as inventory product if it has inventory children product
        inventory_office_product = OfficeProductModel.objects.filter(
            Q(office_id=office_pk) & Q(is_inventory=True) & Q(product_id=OuterRef("pk"))
        )

        return (
            products.prefetch_related(Prefetch("office_products", queryset=office_products, to_attr="office_product"))
            .annotate(office_product_price=Subquery(office_product_price[:1]))
            .annotate(is_inventory=Exists(inventory_office_product))
            # .annotate(last_order_date=Subquery(inventory_office_products.values("last_order_date")[:1]))
            # .annotate(last_order_price=Subquery(inventory_office_products.values("price")[:1]))
            # .annotate(product_vendor_status=Subquery(office_products.values("product_vendor_status")[:1]))
            .annotate(product_price=Coalesce(F("office_product_price"), F("price")))
            .annotate(
                selected_product=Case(
                    When(id__in=selected_products, then=Value(0)),
                    default=Value(1),
                )
            )
            .order_by("product_price")
        )

    @staticmethod
    def get_products_v2(
        office: Union[OfficeModel, SmartID],
        fetch_parents: bool = True,
        product_ids: Optional[List[SmartID]] = None,
        products: Optional[QuerySet] = None,
        selected_products: Optional[List[SmartID]] = None,
    ):
        """
        fetch_parents:  True:   fetch parent products
                        False:  fetch all products
        selected_products: list of product id, product ids in this list will be ordered first
        """
        if isinstance(office, OfficeModel):
            office_pk = office.id
        else:
            office_pk = office

        # get products from vendors that are linked to the office account
        if products is None:
            products = ProductModel.objects.all()

        connected_vendor_ids = OfficeVendorHelper.get_connected_vendor_ids(office_pk)
        products = products.exclude(parent__isnull=True)

        if product_ids is not None:
            products = products.filter(Q(id__in=product_ids))

        products = products.filter(Q(vendor_id__in=connected_vendor_ids))

        if selected_products is None:
            selected_products = []

        parent_product_ids = products.values_list("parent_id", flat=True)
        products = ProductModel.objects.filter(id__in=parent_product_ids).select_related("vendor", "category")

        # TODO: this should be optimized
        office_products = OfficeProductModel.objects.filter(Q(office_id=office_pk))
        office_product = OfficeProductModel.objects.filter(Q(office_id=office_pk) & Q(product_id=OuterRef("pk")))

        # we treat parent product as inventory product if it has inventory children product
        inventory_office_product = OfficeProductModel.objects.filter(
            Q(office_id=office_pk) & Q(is_inventory=True) & Q(product_id=OuterRef("pk"))
        )

        return (
            products.prefetch_related(Prefetch("office_products", queryset=office_products, to_attr="office_product"))
            .annotate(office_product_price=Subquery(office_product.values("price")[:1]))
            .annotate(is_inventory=Exists(inventory_office_product))
            # .annotate(last_order_date=Subquery(inventory_office_products.values("last_order_date")[:1]))
            # .annotate(last_order_price=Subquery(inventory_office_products.values("price")[:1]))
            # .annotate(product_vendor_status=Subquery(office_products.values("product_vendor_status")[:1]))
            .annotate(
                product_price=Coalesce(F("office_product_price"), F("price")),
            )
            .annotate(
                selected_product=Case(
                    When(id__in=selected_products, then=Value(0)),
                    default=Value(1),
                )
            )
            .order_by("selected_product", "-is_inventory", "product_price")
        )

    @staticmethod
    def get_products_v3(
        query: str,
        office: Union[OfficeModel, SmartID],
        fetch_parents: bool = True,
        selected_products: Optional[List[SmartID]] = None,
        price_from: float = -1,
        price_to: float = -1,
        vendors: Optional[List[str]] = None,
    ):
        replacer = Replacer()
        query = replacer.replace(query)
        if isinstance(office, OfficeModel):
            office_pk = office.id
        else:
            office_pk = office

        connected_vendor_ids = list(OfficeVendorHelper.get_connected_vendor_ids(office_pk))
        print("connected_vendor_ids: ", connected_vendor_ids)
        vendor_slugs = vendors.split(",") if vendors else []
        if vendor_slugs:
            selected_vendors = VendorModel.objects.filter(slug__in=vendor_slugs).values_list("id", flat=True)
            connected_vendor_ids = list(set(connected_vendor_ids) & set(selected_vendors))
            print("connected_vendor_ids: ", connected_vendor_ids)
        print("query", query)
        products = (
            ProductModel.objects.available_products()
            .search(query)
            .filter(Q(vendors__overlap=connected_vendor_ids))
            .filter(parent=None)
        )

        # Find by nicknames
        q = SearchQuery(query, config="english")
        office_nickname_products = (
            OfficeProductModel.objects.annotate(
                nn_vector=RawSQL("nn_vector", params=[], output_field=SearchVectorField())
            )
            .filter(office_id=office_pk, nn_vector=q)
            .values_list("product_id", flat=True)
        )
        office_nickname_product_parents = list(
            ProductModel.objects.filter(id__in=office_nickname_products).values_list("parent_id", flat=True)
        )
        office_nickname_products = ProductModel.objects.available_products().filter(
            id__in=office_nickname_product_parents
        )
        print("office_nickname_products", office_nickname_products)
        # Unify with the above
        products = products | office_nickname_products

        # TODO: why don't we remove this one? How is it being used?
        #       Let's change it to office enabled vendors, this query is expensive
        available_vendor_ids = set(v for vendors in products.values_list("vendors", flat=True) for v in vendors)
        available_vendors = [v.slug for v in VendorModel.objects.filter(pk__in=available_vendor_ids)]
        if selected_products is None:
            selected_products = []

        products = products.select_related("vendor", "category")

        office_product_price = OfficeProductModel.objects.filter(
            office_id=office_pk, product_id=OuterRef("pk")
        ).values("price")

        # we treat parent product as inventory product if it has inventory children product
        max_last_order_date = (
            OfficeProductModel.objects.filter(
                office_id=office_pk, is_inventory=True, product__parent_id=OuterRef("pk")
            )
            .order_by()
            .annotate(max_last_order_date=Func(F("last_order_date"), function="Max"))
            .values("max_last_order_date")
        )

        price_least_update_date = timezone.localtime() - datetime.timedelta(days=settings.PRODUCT_PRICE_UPDATE_CYCLE)
        print(price_least_update_date)
        office_product_price = OfficeProductModel.objects.filter(
            Q(office=office) & Q(product_id=OuterRef("pk"))
        ).values("price")

        child_products_prefetch = (
            ProductModel.objects.available_products()
            .select_related("vendor", "category")
            .filter(vendor_id__in=connected_vendor_ids)
            .prefetch_related(
                "images",
                Prefetch(
                    "office_products", OfficeProductModel.objects.filter(office=office), to_attr="office_product"
                ),
            )
            .annotate(office_product_price=Subquery(office_product_price))
            .annotate(
                product_price=Case(
                    When(office_product_price__isnull=False, then=F("office_product_price")),
                    default=F("price"),
                    output_field=DecimalField(),
                )
            )
            # .annotate(product_price=F("office_product_price"))
            .order_by("product_price")
        )
        if price_from != -1:
            child_products_prefetch = child_products_prefetch.filter(product_price__gte=price_from)
        if price_to != -1:
            child_products_prefetch = child_products_prefetch.filter(product_price__lte=price_to)

        products = (
            products.annotate(last_order_date=Subquery(max_last_order_date))
            .annotate(is_inventory=ExpressionWrapper(Q(last_order_date__isnull=False), output_field=BooleanField()))
            # .annotate(last_order_date=Subquery(inventory_office_products.values("last_order_date")[:1]))
            # .annotate(last_order_price=Subquery(inventory_office_products.values("price")[:1]))
            # .annotate(product_vendor_status=Subquery(office_products.values("product_vendor_status")[:1]))
            .annotate(
                selected_product=Case(
                    When(id__in=selected_products, then=Value(0)),
                    default=Value(1),
                )
            )
            .annotate(
                group=Case(
                    When(child_count__gt=1, then=Value(1)),
                    default=Value(0),
                )
            )
            .order_by(
                "selected_product",
                F("last_order_date").desc(nulls_last=True),
                "-relevance",
                "-child_count",
            )
            .prefetch_related(Prefetch("children", child_products_prefetch))
        )

        return products, available_vendors

    @staticmethod
    def suggest_products(search: str, office: Union[OfficeModel, SmartID], vendors=None):
        if vendors is None:
            vendors = []
        if isinstance(office, OfficeModel):
            office = office.id
            # print("office", office)
        # print("vendors =====", vendors)
        # we treat parent product as inventory product if it has inventory children product
        sub_query_filter = Q(is_inventory=True) & Q(product_id=OuterRef("pk"))

        if office:
            sub_query_filter &= Q(office_id=office)
        # print("sub_query_filter", sub_query_filter)
        inventory_products = OfficeProductModel.objects.filter(sub_query_filter)
        # print("inventory_products", inventory_products)
        product_id_search = remove_dash_between_numerics(search)
        product_filter = Q(parent__isnull=True) & (
            Q(name__icontains=search)
            | Q(product_id__icontains=search)
            | Q(product_id__icontains=product_id_search)
            | Q(child__product_id=product_id_search)
        )
        # print("product_filter", product_filter)
        product_query = (
            ProductModel.objects.filter(product_filter)
            .annotate(is_inventory=Exists(inventory_products))
            .filter(Q(vendors__overlap=vendors))
            .distinct()
            .order_by("-is_inventory")
        )
        # print("product_query", product_query)
        return product_query

    # @staticmethod
    # def suggest_products(search: str, office: Union[OfficeModel, SmartID]):
    #     print('number of DB hits (queries) at the beginning', len(connection.queries))
    #     if isinstance(office, OfficeModel):
    #         office = office.id
    #
    #     # Create a subquery to filter OfficeProductModel based on is_inventory and office_id
    #     sub_query_filter = Q(is_inventory=True)
    #     if office:
    #         sub_query_filter &= Q(office_id=office)
    #
    #     # Filter OfficeProductModel with the subquery
    #     inventory_products = OfficeProductModel.objects.filter(sub_query_filter)
    #
    #     # Extract product_ids from inventory_products
    #
    #     inventory_product_ids = inventory_products.values_list('product_id', flat=True)
    #
    #     # Remove dashes between numerics in the search term
    #     product_id_search = remove_dash_between_numerics(search)
    #
    #     # Use a single query to filter ProductModel and annotate with is_inventory
    #     products_query = ProductModel.objects.filter(
    #         Q(parent__isnull=True) & (
    #                 Q(name__icontains=search) |
    #                 Q(product_id__icontains=search) |
    #                 Q(product_id__icontains=product_id_search) |
    #                 Q(child__product_id=product_id_search)
    #         )
    #     ).annotate(
    #         is_inventory=Exists(inventory_products.filter(product_id=OuterRef('pk')))
    #     ).distinct().order_by(F('is_inventory').desc())
    #
    #     # Optionally, you can paginate the results here
    #     print('number of DB hits (queries) at the end', len(connection.queries))
    #
    #     return products_query


class OfficeVendorHelper:
    @staticmethod
    def get_connected_vendor_ids(office: Union[int, str, OfficeModel]) -> List[str]:
        if isinstance(office, OfficeModel):
            office_id = office.id
        else:
            office_id = office
        office_vendors = OfficeVendorModel.objects.filter(office_id=office_id)
        office_vendors.query.clear_ordering()
        return office_vendors.values_list("vendor_id", flat=True)


class ProcedureHelper:
    @staticmethod
    def fetch_procedure_period(day_from, office_id):
        if day_from is None or office_id is None:
            print("Wrong argument(s)")
            return

        office = OfficeModel.objects.get(id=office_id)
        dental_api = office.dental_api
        if not dental_api:
            print("Invalid dental api key")
            return

        date_now = datetime.datetime.now()

        week_startday = day_from - datetime.timedelta(days=day_from.weekday())
        last_week_startday = date_now - datetime.timedelta(days=date_now.weekday())
        for dt in rrule.rrule(rrule.WEEKLY, dtstart=week_startday, until=date_now):
            ProcedureHelper.fetch_procedures(
                dt,
                dt + datetime.timedelta(days=6),
                office.id,
                dental_api.key,
                dt.date() == last_week_startday.date(),
            )

    @staticmethod
    def fetch_procedures(day_from, day_to, office_id, dental_api, force_update=False):
        if day_from is None or day_to is None:
            print("Wrong argument(s)")
            return

        old_procs = ProcedureModel.objects.filter(office=office_id, start_date=day_from)
        bExists = len(old_procs) > 0

        if not force_update and bExists:
            print(f"Already exists with day_from={day_from}")
            return

        with open(settings.BASE_DIR / "query/procedure.sql") as f:
            queryProcedure = f.read()

        query = queryProcedure.format(day_from=day_from, day_to=day_to)
        print(f"Fetching {day_from} - {day_to}")
        offset = 0
        count = 0

        try:
            creating_procedures = []
            while True:
                od_client = OpenDentalClient(dental_api)
                json_procedure, status = od_client.query(query, offset)
                if status != HTTP_200_OK:
                    return Response(status=status, data={"message": f"{json_procedure}"})
                response_len = len(json_procedure)

                print(f"Fetching offset = {offset} length = {response_len}")

                for procedure in json_procedure:
                    procedure_code = ProcedureCodeModel.objects.filter(proccode=procedure["ProcCode"]).first()
                    if procedure_code:
                        creating_procedures.append(
                            ProcedureModel(
                                start_date=day_from,
                                count=int(str(procedure["Count"]).replace(",", "")),
                                avgfee=str(procedure["AvgFee"]).replace(",", ""),
                                totfee=str(procedure["TotFee"]).replace(",", ""),
                                procedurecode=procedure_code,
                                office_id=office_id,
                            )
                        )

                count += response_len
                if response_len == 100:
                    offset += 100
                else:
                    break
            if bExists and force_update:
                old_procs.delete()
            bulk_create(ProcedureModel, creating_procedures)
        except Exception:
            # Skip in case we have a failure from Open Dental or parse issue.
            pass

        print(f"Update {day_from} - {day_to} {count} rows")


class OfficeProductCategoryHelper:
    @staticmethod
    def create_categories_from_product_category(office_id):
        office = OfficeModel.objects.get(pk=office_id)
        product_categories = ProductCategoryModel.objects.all()

        new_categories = [
            OfficeProductCategoryModel(
                office=office,
                name=product_category.name,
                slug=product_category.slug,
            )
            for product_category in product_categories
        ]
        batch_size = 500

        try:
            OfficeProductCategoryModel.objects.bulk_create(new_categories, batch_size, ignore_conflicts=True)
        except Exception as err:
            logger.debug("OfficeProductCategory bulk inserting error: \n")
            raise ValueError(err)


class OrderHelper:
    @staticmethod
    def check_website_status(vendor_slug):
        slug_url_dict = {
            "net_32": "https://www.net32.com/",
            "amazon": "https://www.amazon.com/",
            "implant_direct": "https://www.implantdirect.com/",
            "practicon": "https://www.practicon.com",
            "midwest_dental": "https://www.mwdental.com",
            "ultradent": "https://www.ultradent.com/",
            "dental_city": "https://dentalcity.com/",
            "edge_endo": "https://www.edgeendo.com/",
            "benco": "https://www.benco.com/",
            "patterson": "https://www.pattersondental.com/",
            "darby": "https://www.darbydental.com/",
            "salvin": "https://salvin.com",
            "pearson": "https://www.pearsondental.com",
            "top_glove": "http://topqualitygloves.com/",
            "skydental": "https://www.skydentalsupply.com/",
            "bluesky_bio": "https://blueskybio.com/",
            "bergmand": "https://www.bergmandms.com/",
            "orthoarch": "https://orthoarchshop.com/",
            "atomo": "https://www.atomodental.com",
            "biohorizons": "https://usstore.biohorizons.com/",
            "office_depot": "https://www.officedepot.com",
            "ebay": "https://ebay.com/",
            "safco": "https://www.safcodental.com",
            "henry_schein": "https://www.henryschein.com/",
            "dcdental": "https://www.dcdental.com",
            "crazy_dental": "https://www.crazydentalprices.com",
            "purelife": "https://www.purelifedental.com",
        }
        if slug_url_dict[vendor_slug]:
            url = slug_url_dict[vendor_slug]
        else:
            return Response({"status": "Invalid vendor slug."}, status=400)

        try:
            if vendor_slug != "patterson":
                response = requests.get(url)
            else:
                response = requests.get(url, verify=False)
            logger.info("Website is down, do not proceed with the login")
            if response.status_code == 200:
                status = "Website is up and running."
            else:
                status = "Website is up, but returned status code: " + str(response.status_code)
        except requests.ConnectionError:
            status = "Website is down!"

        return Response({"status": status})

    @staticmethod
    async def _pre_login_steps(vendor_slug):
        # Check the website status
        response = OrderHelper.check_website_status(vendor_slug)
        if response.status_code != 200:
            # Website is down, do not proceed with the login
            return False
        return True

    @staticmethod
    async def login_vendor(office_vendor: OfficeVendorModel, vendor, vendor_slug=None):
        # from apps.accounts.tasks import notify_vendor_auth_issue_to_admins
        if vendor_slug:
            if not await OrderHelper._pre_login_steps(vendor_slug):
                logger.info("Website is down, do not proceed with the login")
                return False

        ret = True
        async with ClientSession(timeout=ClientTimeout(30)) as session:
            scraper = ScraperFactory.create_scraper(
                vendor=vendor,
                session=session,
                username=office_vendor.username,
                password=office_vendor.password,
            )
            try:
                logger.info("Starting login...")
                ret = await scraper.login()
            except Exception as e:
                logger.info("Login failed...", e)
                # Comment this notification out as of now per discussion with clients...
                # notify_vendor_auth_issue_to_admins.delay(office_vendor.id)
                ret = False

        logger.info("Login vendor returning result...")
        return ret

    @staticmethod
    @inject_session(handler=upload_and_notify_order_fetch_session)
    async def fetch_orders_and_update(
        office_vendor: OfficeVendorModel,
        login_cookies: str = None,
        perform_login: bool = True,
        completed_order_ids: Optional[list] = None,
        consider_recent: bool = False,
        session: ClientSession = None,
    ):
        if completed_order_ids is None:
            completed_order_ids = []
        if office_vendor.vendor.slug in API_AVAILABLE_VENDORS and office_vendor.vendor.slug == "crazy_dental":
            api_client = APIClientFactory.get_api_client(vendor=office_vendor.vendor, session=session)
            await api_client.get_orders(
                office=office_vendor.office,
                # from_date=from_date,
                # to_date=to_date,
                # perform_login=False,
                completed_order_ids=completed_order_ids,
            )
            print("****************************************done")
            return
        scraper = ScraperFactory.create_scraper(
            vendor=office_vendor.vendor,
            session=session,
            username=office_vendor.username,
            password=office_vendor.password,
        )

        to_date = timezone.localtime().date()
        if consider_recent:
            from_date = timezone.localtime().date() - datetime.timedelta(days=4)
        else:
            from_date = to_date.replace(year=to_date.year - 2)

        if perform_login:
            try:
                await scraper.login()
            except Exception:
                office_vendor.login_success = False
                await office_vendor.asave()
                raise VendorAuthFailed(f"Authentication is failed for {office_vendor.vendor.name} vendor")

        await scraper.get_orders(
            office=office_vendor.office,
            from_date=from_date,
            to_date=to_date,
            perform_login=False,
            completed_order_ids=completed_order_ids,
        )

    @staticmethod
    @inject_session(handler=upload_and_notify_vendor_order_session)
    async def process_order_in_vendor(
        vendor_order: VendorOrderModel,
        office_vendor: OfficeVendorModel,
        products: List[CartProduct],
        fake_order: bool = False,
        perform_login: bool = True,
        session: ClientSession = None,
    ):
        if vendor_order.vendor.slug in API_AVAILABLE_VENDORS:
            api_client = APIClientFactory.get_api_client(vendor=vendor_order.vendor, session=session)
            await api_client.place_order(office_vendor, vendor_order, products)

            return
        scraper = ScraperFactory.create_scraper(
            vendor=office_vendor.vendor,
            session=session,
            username=office_vendor.username,
            password=office_vendor.password,
        )
        if perform_login:
            try:
                await scraper.login()
            except Exception:
                logger.debug(f"Authentication is failed for {office_vendor.vendor.name} vendor")
                raise
        scraper.office = office_vendor.office
        result = await scraper.confirm_order(
            products=products,
            shipping_method=vendor_order.shipping_option.name if vendor_order.shipping_option else "",
            fake=fake_order,
        )

        if result.get("order_type") is msgs.ORDER_TYPE_ORDO:
            cancelled_ids = result.get("cancel_ids", [])
            vendor_order.vendor_order_id = result.get("order_id")
            async for cancel_product in vendor_order.order_products.filter(product__product_id__in=cancelled_ids):
                cancel_product.status = ProductStatus.CANCELLED
                await cancel_product.asave()
            await vendor_order.asave()
            await sync_to_async(OrderHelper.update_vendor_order_totals)(vendor_order)

    @staticmethod
    async def perform_orders_in_vendors(
        order_id: int,
        vendor_order_ids: List[int],
        fake_order: bool = False,
    ):
        order = await OrderModel.objects.aget(pk=order_id)
        order_tasks = []
        for vendor_order_id in vendor_order_ids:
            vendor_order = (
                await VendorOrderModel.objects.select_related("order", "order__office", "shipping_option", "vendor")
                .prefetch_related("order_products")
                .aget(pk=vendor_order_id)
            )
            vendor_order_products = (
                vendor_order.order_products.select_related("product").filter(status=ProductStatus.PROCESSING).all()
            )
            office_vendor = (
                await OfficeVendorModel.objects.select_related("vendor", "office", "office__company")
                .prefetch_related("office__addresses")
                .aget(office_id=vendor_order.order.office_id, vendor_id=vendor_order.vendor_id)
            )
            products = []

            async for vendor_order_product in vendor_order_products:
                product_description = (
                    vendor_description
                    if (vendor_description := vendor_order_product.product.vendor_description)
                    else vendor_order_product.product.description
                )
                products.append(
                    CartProduct(
                        product_id=vendor_order_product.product.product_id,
                        product_description=product_description,
                        product_unit=vendor_order_product.product.product_unit,
                        product_url=vendor_order_product.product.url,
                        price=float(vendor_order_product.unit_price) if vendor_order_product.unit_price else 0.0,
                        quantity=int(vendor_order_product.quantity),
                        sku=vendor_order_product.product.sku,
                        manufacturer_number=vendor_order_product.product.manufacturer_number,
                    )
                )
                await OfficeProductModel.objects.filter(
                    office=vendor_order.order.office, product=vendor_order_product.product
                ).aupdate(last_order_date=vendor_order.order_date)

            order_tasks.append(
                OrderHelper.process_order_in_vendor(
                    vendor_order=vendor_order,
                    office_vendor=office_vendor,
                    products=products,
                    fake_order=fake_order,
                    handler_context={"vendor_order_id": vendor_order.id},
                )
            )
        results = await aio.gather(*order_tasks, return_exceptions=True)
        for vendor_order_id, result in zip(vendor_order_ids, results):
            if isinstance(result, Exception):
                summary = traceback.extract_tb(result.__traceback__)
                exception_tb = "\n".join(summary.format())
                logger.error(
                    "Placing vendor order %s resulted in exception:\n%s\n%s",
                    vendor_order_id,
                    result,
                    exception_tb,
                )
                notify(text=f"Placing vendor order {vendor_order_id} resulted in exception")
            elif isinstance(result, TracedSession):
                upload_traced_session(result, vendor_order_id)

        if any([isinstance(r, Exception) for r in results]):
            return

        order = await OrderModel.objects.aget(pk=order_id)
        order.order_type = OrderType.ORDO_ORDER
        await sync_to_async(order.save)()

    @staticmethod
    def update_order_totals(order: OrderModel):
        new_total_amount = 0
        for vendor_order in VendorOrderModel.objects.filter(order=order):
            new_total_amount += vendor_order.total_amount

        order.total_amount = new_total_amount
        order.save(update_fields=["total_amount"])

    @staticmethod
    def update_vendor_order_totals(vendor_order: VendorOrderModel, total_amount=0):
        new_total_amount = 0
        for vendor_order_product in VendorOrderProductModel.objects.filter(vendor_order=vendor_order).exclude(
            status__in=(
                ProductStatus.REJECTED,
                ProductStatus.CANCELLED,
            )
        ):
            updated_product_price = (
                OfficeProductModel.objects.filter(
                    office_id=vendor_order.order.office_id, product_id=vendor_order_product.product_id
                )
                .values("price")
                .first()
            )
            if not updated_product_price or updated_product_price["price"] is None:
                updated_product_price = (
                    ProductModel.objects.filter(id=vendor_order_product.product_id).values("price").first()
                )
            if not updated_product_price or updated_product_price["price"] is None:
                logger.warning(
                    "Vendor order product %s does not have update price information", vendor_order_product.id
                )
                continue
            new_total_amount += updated_product_price["price"] * vendor_order_product.quantity
        if new_total_amount == 0:
            new_total_amount = total_amount
        if vendor_order.total_amount != new_total_amount:
            total_amount_delta = new_total_amount - vendor_order.total_amount
            vendor_order.total_amount = new_total_amount
            vendor_order.save(update_fields=["total_amount"])
            vendor_order.order.total_amount += total_amount_delta
            vendor_order.order.save(update_fields=["total_amount"])

    @classmethod
    def update_vendor_order_product_price(cls, vendor_slug, office_id=None) -> None:
        pending_vendor_orders = VendorOrderModel.objects.filter(
            vendor__slug=vendor_slug, status=OrderStatus.PENDING_APPROVAL
        )
        if office_id is not None:
            pending_vendor_orders = pending_vendor_orders.filter(order__office_id=office_id)
        for vendor_order in pending_vendor_orders:
            cls.update_vendor_order_totals(vendor_order)
