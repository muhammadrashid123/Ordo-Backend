import datetime
import itertools
import os
import re
import uuid
from decimal import Decimal
from typing import Any, List, Optional, Tuple, Type, Union

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db.models import Model
from django.utils import timezone

CUSTOM_DATE_FILTER = (
    ("thisMonth", "This month"),
    ("lastMonth", "Last month"),
    ("thisQuarter", "This quarter"),
    ("lastQuarter", "Last quarter"),
    ("thisYear", "This year"),
    ("lastYear", "Last year"),
)


def generate_token():
    return uuid.uuid4().hex + uuid.uuid4().hex


def get_similarity(*products, key=None):
    total_words = set()
    matched_words = set()
    total_numeric_values = set()
    matched_numeric_values = set()

    for product_i, product in enumerate(products):
        product_name = product if isinstance(product, str) else getattr(product, key)
        product_numeric_values = set(map(str.lower, re.findall(r"\w*[\d]+\w*", product_name)))
        product_words = set(map(str.lower, re.findall(r"\w+", product_name)))
        product_words = product_words - product_numeric_values
        product_words -= {"of", "and", "with"}
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


def group_products(vendors_search_result_products, model=False):
    search_result_vendors_count = len(vendors_search_result_products)
    matched_products = set()
    well_matching_pairs = set()
    # a list of candidate products which are similar
    similar_candidate_products = []
    products = []
    n_similarity = 2
    threshold = 0.6
    while n_similarity <= search_result_vendors_count:
        vendors_products_combinations = itertools.combinations(vendors_search_result_products, n_similarity)
        for vendors_products_combination in vendors_products_combinations:
            for vendor_products in itertools.product(*vendors_products_combination):
                # when finding more than 3-length similar products we need to check that
                # sub-set of products belongs to well matching pairs. If well matching set contains subset of products
                # it is worth to check similarity but otherwise, we don't have to calculate it.
                if n_similarity > 2:
                    contains_well_matching_pair = any(
                        [
                            set(well_matching_pair).issubset(vendor_products)
                            for well_matching_pair in well_matching_pairs
                        ]
                    )
                    if not contains_well_matching_pair:
                        continue

                similarity = get_similarity(*vendor_products, key="name")
                if similarity > threshold:
                    similar_candidate_products.append((f"{similarity:.2f}", *vendor_products))
                    well_matching_pairs.add(vendor_products)

        n_similarity += 1

    for similar_candidate_product in sorted(similar_candidate_products, key=lambda x: (len(x), x[0]), reverse=True):
        similar_candidate_product_without_similarity = similar_candidate_product[1:]
        for product in similar_candidate_product_without_similarity:
            if product in matched_products:
                break
        else:
            matched_products.update(similar_candidate_product_without_similarity)
            if model:
                parent_product = [
                    product for product in similar_candidate_product_without_similarity if product.parent is None
                ][0]
                # parent_product.children.clear()
                parent_product.children.set(
                    [product for product in similar_candidate_product_without_similarity if product != parent_product]
                )
            else:
                parent_product = similar_candidate_product_without_similarity[0]
                parent_product = parent_product.to_dict()
                products.append(
                    {
                        "price": parent_product.pop("price"),
                        "product": parent_product,
                    }
                )
                parent_product["children"] = [
                    {"price": (p_ := p.to_dict()).pop("price"), "product": p_}
                    for p in similar_candidate_product_without_similarity[1:]
                ]

    if model:
        return True
    else:
        for vendor_search_result_products in vendors_search_result_products:
            for vendor_product in vendor_search_result_products:
                if vendor_product not in matched_products:
                    products.append(
                        {
                            "price": (p := vendor_product.to_dict()).pop("price"),
                            "product": p,
                        }
                    )

        return products


def group_products_from_search_result(search_results):
    meta = {
        "total_size": 0,
        "vendors": [],
    }

    vendors_search_result_products = []
    for search_result in search_results:
        if not isinstance(search_result, dict):
            continue
        meta["total_size"] += search_result["total_size"]
        meta["vendors"].append(
            {
                "vendor": search_result["vendor_slug"],
                "page": search_result["page"],
                "last_page": search_result["last_page"],
            }
        )
        if len(search_result["products"]):
            vendors_search_result_products.append(search_result["products"])

    meta["last_page"] = all([vendor_search["last_page"] for vendor_search in meta["vendors"]])

    products = group_products(vendors_search_result_products)
    return meta, products


def group_products_by_str():
    net32_products = [
        "Septocaine Articaine 4% with Epinephrine 1:100,000. Box of 50 - 1.7 mL",
        "Septocaine Articaine HCl 4% with Epinephrine 1:200,000. Box of 50 - 1.7 mL",
        "Orabloc Articaine HCl 4% with Epinephrine 1:100,000 Injection Cartridges, 1.8",
        "House Brand Articaine HCl 4% with Epinephrine 1:100,000 Injection Cartridges",
        "Orabloc Articaine HCl 4% with Epinephrine 1:200,000 Injection Cartridges, 1.8",
        "Cook-Waite Zorcaine (Articaine Hydrochloride 4%) Local Anesthetic",
        "House Brand Articaine HCl 4% with Epinephrine 1:200,000 Injection Cartridges",
    ]
    henry_products = [
        "Septocaine Articaine HCl 4% Epinephrine 1:200,000 50/Bx",
        "Articadent Articaine HCl 4% Epinephrine 1:100,000 50/Bx",
        "Articaine HCl 4% Epinephrine 1:100,000 50/Bx",
        "Orabloc Articaine HCl 4% Epinephrine 1:200,000 50/Bx",
        "Articaine HCl 4% Epinephrine 1:200,000 50/Bx",
    ]
    benco_products = [
        "Septocaine® Articaine HCl 4% and Epinephrine 1:200,000 Silver Box of 50",
        "Septocaine® Articaine HCl 4% and Epinephrine 1:100,000 Gold Box of 50",
        "SNAP Liquid Monomer 4oz.",
        "Hemodent® Liquid 10cc",
        "IRM Ivory Powder Immediate Restorative Material 38gm",
        "Wizard Wedges® Matrix Small Wedges Pack of 500",
        "Benco Dental™ Non-Skid Base Mix Pads 3” x 3” Pad of 50 Sheets",
        "Dr. Thompson's Applicator Pack of 100",
        'Econoback™ Patient Bib 13" x 19" Blue 3-Ply Case of 500',
        'Benco Dental™ Cotton Tip Applicators 6" Box of 1000',
        "Cook-Waite Lidocaine 1:100,000 Red Box of 50",
        "Jeltrate® Alginate Impression Material Fast Set Pink 1 pound package",
        "IRM COMB P&L IVORY",
        "Dental Floss Waxed Mint 200yd Refill",
    ]

    similarities = []
    for products in itertools.product(*net32_products, henry_products, benco_products):
        similarity = get_similarity(*products)
        similarities.append((f"{similarity:.2f}", *products))

    for i in sorted(similarities, key=lambda x: x[0], reverse=True)[:10]:
        print(i)


def get_week_count(date_range: str):
    start, end = get_date_range(date_range)
    days = (end - start).days + 1
    return days / 7


def get_date_range(date_range: str) -> Tuple[datetime.date, datetime.date]:
    today = timezone.localtime().date()
    first_day_of_this_week = today - datetime.timedelta(days=today.weekday())
    first_day_of_next_week = first_day_of_this_week + relativedelta(weeks=1)
    last_day_of_this_week = first_day_of_this_week + datetime.timedelta(days=6)
    last_day_of_next_week = last_day_of_this_week + relativedelta(weeks=1)
    last_day_of_next_2weeks = last_day_of_this_week + relativedelta(weeks=2)
    last_day_of_next_3weeks = last_day_of_this_week + relativedelta(weeks=3)
    last_day_of_next_4weeks = last_day_of_this_week + relativedelta(weeks=4)
    first_day_of_this_month = today.replace(day=1)
    first_day_of_this_year = datetime.date(year=today.year, month=1, day=1)
    first_day_of_this_quarter = datetime.date(
        year=first_day_of_this_month.year, month=(first_day_of_this_month.month - 1) // 3 * 3 + 1, day=1
    )
    first_day_of_last_quarter = first_day_of_this_quarter - relativedelta(months=3)
    first_day_of_last_year = datetime.date(year=today.year - 1, month=1, day=1)
    first_day_of_last_month = first_day_of_this_month - relativedelta(months=1)
    last_day_of_last_month = first_day_of_this_month - relativedelta(days=1)
    first_day_of_last_2_months = first_day_of_this_month - relativedelta(months=2)
    first_day_of_last_3_months = first_day_of_this_month - relativedelta(months=3)
    first_day_of_last_12_months = first_day_of_this_month - relativedelta(months=12)

    last_day_of_last_year = datetime.date(year=today.year - 1, month=12, day=31)

    ret = {
        "thisWeek": (first_day_of_this_week, last_day_of_this_week),
        "nextWeek": (first_day_of_next_week, last_day_of_next_week),
        "next2Weeks": (first_day_of_next_week, last_day_of_next_2weeks),
        "next3Weeks": (first_day_of_next_week, last_day_of_next_3weeks),
        "next4Weeks": (first_day_of_next_week, last_day_of_next_4weeks),
        "thisMonth": (first_day_of_this_month, today),
        "thisQuarter": (first_day_of_this_quarter, today),
        "lastQuarter": (first_day_of_last_quarter, today),
        "lastMonth": (first_day_of_last_month, last_day_of_last_month),
        "last2Months": (first_day_of_last_2_months, last_day_of_last_month),
        "last3Months": (first_day_of_last_3_months, last_day_of_last_month),
        "thisYear": (first_day_of_this_year, today),
        "last12Months": (first_day_of_last_12_months, last_day_of_last_month),
        "lastYear": (first_day_of_last_year, last_day_of_last_year),
    }

    return ret.get(date_range)


def bulk_create(model_class: Model, objs: List[Model], batch_size=500) -> List[Model]:
    instances = []
    for i in range(0, len(objs), batch_size):
        batch = objs[i : i + batch_size]
        instances.extend(model_class.objects.bulk_create(batch, batch_size))
    return instances


def bulk_update(model_class: Type[Model], objs: List[Model], fields: List[str], batch_size=500):
    for i in range(0, len(objs), batch_size):
        batch = objs[i : i + batch_size]
        model_class.objects.bulk_update(batch, fields, batch_size)


def find_numeric_values_from_string(s):
    return re.findall(r"\w*[\d]+\w*", s)


def find_numerics_from_string(text: str) -> List[str]:
    return re.findall(r"(\d[\d.,]*)\s*", text)


def find_words_from_string(s):
    return re.findall(r"\w+", s)


def extract_numeric_values(text: str) -> List[str]:
    return re.findall(r"(\d[\d.,]*)\s*", text)


def find_prices_from_string(text: str) -> List[str]:
    return re.findall(r"\$(\d[\d.,]*)\s*", text)


def remove_dash_between_numerics(text: str) -> str:
    if mo := re.match(r"(\d+)-(\d+)", text):
        return "{}{}".format(mo.group(1), mo.group(2))
    return text


def convert_string_to_price(text: str) -> Decimal:
    try:
        price = extract_numeric_values(text)[0]
        price = price.replace(",", "")
        return Decimal(price)
    except (KeyError, ValueError, TypeError, IndexError):
        return Decimal("0")


def extract_price_from_string(text: str) -> Decimal:
    try:
        price = find_prices_from_string(text)[0]
        price = price.replace(",", "")
        return Decimal(price)
    except (KeyError, ValueError, TypeError, IndexError):
        return Decimal("0")


def extract_integer_from_string(text: str) -> int:
    try:
        price = find_numerics_from_string(text)[0]
        price = price.replace(",", "")
        return int(price)
    except (KeyError, ValueError, TypeError, IndexError):
        return 0


def get_file_name_and_ext(file_path: str) -> Tuple[str, str]:
    file_name = file_path.split(os.path.sep)[-1]
    file_name, ext = file_name.split(".")
    return file_name, ext


def sort_and_write_to_csv(
    fie_path_or_data_frame: Union[pd.DataFrame, str], columns: List[str], file_name: Optional[str] = None
):
    if isinstance(fie_path_or_data_frame, str):
        df = pd.read_csv(fie_path_or_data_frame)
    else:
        df = fie_path_or_data_frame

    sorted_df = df.sort_values(by=columns)
    sorted_df.to_csv(file_name or "sorted.csv", index=False)
    return df


def concatenate_strings(text: List[str], delimeter="") -> str:
    return delimeter.join(map(str.strip, text))


def strip_whitespaces(text: str) -> str:
    """Remove spaces, tabs and new lines"""
    return re.sub(r"\s+", " ", text).strip()


def concatenate_list_as_string(objs: List[Any], delimiter="") -> str:
    return delimiter.join(filter(lambda x: x, map(strip_whitespaces, map(str, objs))))


def formatStEndDateFromQuery(jsonQuery, st, end):
    newvalue = jsonQuery["SqlCommand"].format(value1=st, value2=end)
    return newvalue


def batched(iterable, size):
    it = iter(iterable)
    while item := list(itertools.islice(it, size)):
        yield item


def normalize_order_status(order_status):
    if order_status is None:
        return "closed"

    order_status = order_status.lower()
    if any(status in order_status for status in ("delivered", "complete", "cancelled", "closed")):
        return "closed"
    if order_status == "pendingapproval":
        return "pendingapproval"
    return "open"


def normalize_product_status(product_status):
    product_status = product_status.lower()
    return product_status


def clean_text(xpath, dom):
    return re.sub(r"\s+", " ", " ".join(dom.xpath(xpath).extract())).strip()


if __name__ == "__main__":
    group_products_by_str()
