import copy
import datetime
import decimal
import itertools
from collections import defaultdict
from itertools import chain
from typing import List, Optional, Union

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import transaction
from django.db.models import Model
from django.db.models.query import QuerySet

from apps.common.utils import (
    bulk_update,
    find_numeric_values_from_string,
    find_words_from_string,
)
from apps.orders.models import Product, ProductCategory, ProductImage, Vendor

ProductID = Union[int, str]
ProductIDs = List[ProductID]


def clean_price(price: str) -> Optional[decimal.Decimal]:
    if price is None:
        return None
    if isinstance(price, str):
        cleaned_price = price.replace(",", "")
        return decimal.Decimal(cleaned_price)


class ProductService:
    @staticmethod
    def get_or_create_parent_id(product: Product) -> int:
        manufacturer_number = product.manufacturer_number
        if not manufacturer_number:
            return None

        query = SearchQuery(product.name, config="english")
        most_similar_product = (
            Product.objects.filter(manufacturer_number=manufacturer_number, parent_id__isnull=False)
            .annotate(rank=SearchRank("search_vector", query))
            .filter(rank__gt=0.1)
            .only("parent_id")
            .first()
        )
        if most_similar_product:
            return most_similar_product.parent_id

        # Similar not found, let's create new one
        parent = Product.objects.create(
            name=product.name,
            category_id=product.category_id,
        )
        return parent.id

    @staticmethod
    def group_products(product_ids: Optional[ProductID] = None):
        """Group products"""

        # In the future, we shouldn't perform group again for already grouped products,
        # but for now, we can perform this operation for all products
        products = Product.objects.filter(parent__isnull=False)
        for product in products:
            product.parent = None
        bulk_update(Product, products, fields=["parent"])

        products = Product.objects.all()
        if product_ids:
            products = products.filter(id__in=product_ids)

        vendor_slugs = products.order_by("vendor").values_list("vendor__slug", flat=True).distinct()
        if len(vendor_slugs) <= 1:
            # if the products are from one vendor, don't need to proceed further
            return None

        # get the list of similar product ids by product category
        product_categories = ProductCategory.objects.all().order_by("name")
        for product_category in product_categories:
            print(f"Group {product_category} products")
            ProductService.group_products_by_category(products, product_category)

    @staticmethod
    def group_products_by_category(
        products: QuerySet, product_category: Optional[ProductCategory] = None
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

        vendor_products = []
        for vendor_slug in vendor_slugs:
            vendor_products_names = products.filter(vendor__slug=vendor_slug).values("id", "vendor", "name")
            if product_category:
                vendor_products_names = products.filter(category=product_category)

            if vendor_products_names:
                vendor_products.append(vendor_products_names)

        if len(vendor_products) <= 1:
            return []

        similar_product_ids_list = ProductService.group_products_by_name(vendor_products)

        updated_products = []
        for similar_product_ids in similar_product_ids_list:
            similar_products = products.filter(id__in=similar_product_ids)
            parent_products = similar_products.filter(child__isnull=False)

            if parent_products:
                parent_product = parent_products[0]
                similar_products = [
                    similar_product for similar_product in similar_products if similar_product.id != parent_product.id
                ]
                for similar_product in similar_products:
                    similar_product.parent = parent_product
                for other_parent_product in parent_products[1:]:
                    for child_product in other_parent_product.children.all():
                        child_product.parent = parent_product

                updated_products.extend(similar_products)
            else:
                parent_product = similar_products[0]
                similar_products = [
                    similar_product for similar_product in similar_products if similar_product.id != parent_product.id
                ]
                for similar_product in similar_products:
                    similar_product.parent = parent_product
                updated_products.extend(similar_products)

        print(updated_products)
        bulk_update(Product, updated_products, fields=["parent"])

    @staticmethod
    def group_products_by_name(product_names_list) -> List[ProductIDs]:
        threshold = 0.65
        n_similarity = 2
        vendors_count = len(product_names_list)
        similar_products_candidates = defaultdict(list)

        # find out all 2-length similar products
        products_combinations = itertools.combinations(product_names_list, n_similarity)
        for products_combination in products_combinations:
            for vendor_products in itertools.product(*products_combination):
                vendor_product_names = [vendor_product["name"] for vendor_product in vendor_products]
                similarity = ProductService.get_similarity(*vendor_product_names)
                if similarity > threshold:
                    display_text = "; ".join(
                        [
                            f'{vendor_product["name"]} from {vendor_product["vendor"]}'
                            for vendor_product in vendor_products
                        ]
                    )
                    print(f"{similarity:.2f}: {display_text}")
                    similar_products_candidates[n_similarity].append([f"{similarity:.2f}", *vendor_products])

        # when finding more than 3-length similar products we need to check from candidates pairs
        n_similarity = 3
        while n_similarity <= vendors_count:
            n_threshold = threshold ** (n_similarity - 1)
            n_1_similarity_products_pairs_length = len(similar_products_candidates[n_similarity - 1])
            if not n_1_similarity_products_pairs_length:
                break

            well_matching_pair_ids = set()
            for i in range(n_1_similarity_products_pairs_length - 1):
                ith_similar_products_pair = similar_products_candidates[n_similarity - 1][i][1:]
                ith_similar_product_ids = set([product["id"] for product in ith_similar_products_pair])
                ith_similar_product_vendors = set([product["vendor"] for product in ith_similar_products_pair])
                for j in range(i + 1, n_1_similarity_products_pairs_length):
                    jth_similar_products_pair = similar_products_candidates[n_similarity - 1][j][1:]
                    jth_similar_product_ids = set([product["id"] for product in jth_similar_products_pair])
                    jth_similar_product_vendors = set([product["vendor"] for product in jth_similar_products_pair])
                    if not ith_similar_product_ids.intersection(jth_similar_product_ids):
                        continue

                    ith_vendor_difference = ith_similar_product_vendors - jth_similar_product_vendors
                    jth_vendor_difference = jth_similar_product_vendors - ith_similar_product_vendors

                    if ith_vendor_difference == jth_vendor_difference:
                        continue

                    if tuple(ith_similar_product_ids | jth_similar_product_ids) in well_matching_pair_ids:
                        continue

                    well_matching_pair_ids.add(tuple(ith_similar_product_ids | jth_similar_product_ids))
                    similar_products_pair = copy.deepcopy(ith_similar_products_pair)
                    similar_products_pair.extend(
                        [
                            product
                            for product in jth_similar_products_pair
                            if product["id"] in jth_similar_product_ids - ith_similar_product_ids
                        ]
                    )

                    vendor_product_names = [product["name"] for product in similar_products_pair]
                    display_text = "; ".join(
                        [
                            f'{vendor_product["name"]} from {vendor_product["vendor"]}'
                            for vendor_product in similar_products_pair
                        ]
                    )
                    similarity = ProductService.get_similarity(*vendor_product_names)

                    if similarity > n_threshold:
                        print(f"{similarity:.2f}: {display_text}")
                        similar_products_candidates[n_similarity].append([f"{similarity:.2f}", *similar_products_pair])

            n_similarity += 1

        similar_products_candidates = chain.from_iterable([value for _, value in similar_products_candidates.items()])
        similar_products_list = ProductService.clean_well_matching_paris(similar_products_candidates)
        return [[product["id"] for product in similar_products[1:]] for similar_products in similar_products_list]

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
            well_matching_product_pair_ids = set([product["id"] for product in well_matching_pair[1:]])
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
    def generate_products_from_data(products, vendor_slug):
        """
        Create products in the Product table with a list of product json data
        and the given vendor slug.
        :param products: List[dict] - a list of product data to be created in Product table
        :param vendor_slug: str - literally the vendor slug
        :return: none
        """
        if not products:
            return

        vendor = Vendor.objects.filter(slug=vendor_slug).first()
        image_data = {p["product_id"]: p.pop("images") for p in products}
        overall_ids = [p["product_id"] for p in products]
        products_to_update = Product.objects.filter(product_id__in=overall_ids)
        update_products_map = {u.product_id: u for u in products_to_update}
        two_days_ago = datetime.datetime.now() - datetime.timedelta(days=2)
        products_to_create = []
        image_products_to_create = []

        for product in products:
            if product["product_id"] in update_products_map.keys():
                if update_products_map[product["product_id"]].updated_at.date() >= two_days_ago.date():
                    continue
                update_products_map[product["product_id"]].price = clean_price(product["price"])
                update_products_map[product["product_id"]].url = product["url"]
                update_products_map[product["product_id"]].name = product["name"]
                update_products_map[product["product_id"]].description = product["description"]

                if (
                    not update_products_map[product["product_id"]].images.exists()
                    and image_data[product["product_id"]][0]["image"]
                ):
                    image_products_to_create.append(
                        ProductImage(
                            product=update_products_map[product["product_id"]],
                            image=image_data[product["product_id"]][0]["image"],
                        )
                    )
            else:
                product["vendor"] = vendor
                products_to_create.append(Product(**product))

        try:
            # NOTE: Need to consider batch size when upgrading the search engine later....
            with transaction.atomic():
                created_products = Product.objects.bulk_create(
                    products_to_create,
                )

                for cp in created_products:
                    image_products_to_create.append(
                        ProductImage(product=cp, image=image_data[cp.product_id][0]["image"])
                    )
                ProductImage.objects.bulk_create(
                    image_products_to_create,
                )
                Product.objects.bulk_update(products_to_update, ["price", "url", "name", "description"])
        except Exception as err:
            raise ValueError(err)
