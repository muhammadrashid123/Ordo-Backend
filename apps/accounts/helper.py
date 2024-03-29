import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Literal, Optional, Union

from django.db.models import (
    Case,
    DurationField,
    ExpressionWrapper,
    F,
    IntegerField,
    OrderBy,
    Prefetch,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework.status import HTTP_200_OK

from apps.accounts.constants import DEFAULT_FRONT_OFFICE_BUDGET_VENDORS
from apps.accounts.models import (
    BUILTIN_BUDGET_SLUGS,
    DEFAULT_PERCENTAGE,
    DEFAULT_PERCENTAGE_MAPPING,
    Budget,
    Office,
)
from apps.accounts.models import OfficeVendor as OfficeVendorModel
from apps.accounts.models import ShippingMethod as ShippingMethodModel
from apps.accounts.models import Subaccount
from apps.accounts.models import Vendor as VendorModel
from apps.common.choices import BUDGET_SPEND_TYPE
from apps.common.month import Month
from apps.common.utils import bulk_create
from apps.orders.models import Order, VendorOrderProduct
from config.constants import ALL_VENDORS
from services.opendental import OpenDentalClient

logger = logging.getLogger(__name__)

SlugType = Literal["dental", "office", "miscellaneous"]


def get_vendor_budget_slug(vendor_slug: str) -> str:
    if vendor_slug == "amazon":
        return "office"
    return "dental"


class BudgetwiseSpend(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, *kwargs)
        self.default_factory = Decimal


class OfficeBudgetHelper:
    @staticmethod
    def update_spend(office: Union[int, str, Office], date: datetime.date, amount: Decimal, slug="dental"):
        month = Month(year=date.year, month=date.month)
        Subaccount.objects.filter(budget__office=office, budget__month=month, slug=slug).update(
            spend=F("spend") + amount
        )

    @staticmethod
    def move_spend_category(
        office: Union[int, str, Office],
        date: datetime.date,
        amount: Decimal,
        from_category: BUDGET_SPEND_TYPE,
        to_category: BUDGET_SPEND_TYPE,
    ) -> bool:
        """This function will move spend from one category to other category"""
        if not from_category or not to_category or from_category == to_category:
            return False
        month = Month.from_date(date)
        budget = OfficeBudgetHelper.get_or_create_budget(office_id=office, month=month)
        actions = ((from_category, -amount), (to_category, amount))
        for category, delta in actions:
            subaccount = OfficeBudgetHelper.get_or_create_subaccount(budget, category)
            subaccount.spend += delta
            subaccount.save(update_fields=["spend"])
        return True

    @staticmethod
    def clone_budget(budget: Budget, overrides: Optional[dict] = None) -> Budget:
        if overrides is None:
            overrides = {}
        new_budget = Budget.objects.create(
            month=overrides.get("month", budget.month.next_month()),
            office_id=budget.office_id,
            basis=overrides.get("basis", budget.basis),
            adjusted_production=overrides.get("adjusted_production", budget.adjusted_production),
            collection=overrides.get("collection", budget.collection),
        )
        subaccounts_to_create = []
        for subaccount in budget.subaccounts.all():
            new_subaccount = Subaccount(
                budget=new_budget,
                slug=subaccount.slug,
                name=subaccount.name,
                vendors=subaccount.vendors,
                percentage=subaccount.percentage,
                spend=0,
            )
            subaccounts_to_create.append(new_subaccount)
        Subaccount.objects.bulk_create(subaccounts_to_create)
        return new_budget

    @staticmethod
    def clone_prev_month_budget(prev_budgets: List[Budget], dental_api_data: Optional[dict] = None):
        if dental_api_data is None:
            dental_api_data = {}
        budgets_to_create = []
        for prev_budget in prev_budgets:
            dental_api_values = dental_api_data.get(prev_budget.office_id, {})
            current_month_budget = Budget(
                month=prev_budget.month.next_month(),
                office_id=prev_budget.office_id,
                basis=prev_budget.basis,
                adjusted_production=dental_api_values.get("adjusted_production", prev_budget.adjusted_production),
                collection=dental_api_values.get("collection", prev_budget.collection),
            )
            budgets_to_create.append(current_month_budget)
        created_budgets = {b.office_id: b for b in Budget.objects.bulk_create(budgets_to_create)}
        subaccounts_to_create = []
        for budget in prev_budgets:
            for subaccount in budget.subaccounts.all():
                new_subaccount = Subaccount(
                    budget=created_budgets[budget.office_id],
                    slug=subaccount.slug,
                    percentage=subaccount.percentage,
                    spend=0,
                    name=subaccount.name,
                    vendors=subaccount.vendors,
                )
                subaccounts_to_create.append(new_subaccount)
        Subaccount.objects.bulk_create(subaccounts_to_create)

    @staticmethod
    def update_budget_with_previous_month():
        # TODO: update budget for active offices
        current_month = Month.from_date(timezone.localdate())
        previous_month = current_month.prev_month()
        current_budgets = Budget.objects.filter(month=previous_month).prefetch_related("subaccounts")
        OfficeBudgetHelper.clone_prev_month_budget(current_budgets)

    @staticmethod
    def update_office_budgets():
        # TODO: create budgets for active offices from Open Dental, if not, from previous month
        current_month = Month.from_date(timezone.localdate())
        last_day_of_prev_month = date.today().replace(day=1) - timedelta(days=1)
        start_day_of_prev_month = date.today().replace(day=1) - timedelta(days=last_day_of_prev_month.day)

        # TODO: test if the .exclude() really works as expected, use annotate if necessary
        prev_month_office_budgets = Budget.objects.filter(month=current_month - 1)
        offices = (
            Office.objects.annotate(dental_api_key=F("dental_api__key"))
            .exclude(budget_set__month=current_month)
            .prefetch_related(Prefetch("budget_set", queryset=prev_month_office_budgets, to_attr="previous_budget"))
        )

        opendental_data = {}
        for office in offices:
            if not office.dental_api_key:
                continue
            try:
                prev_adjusted_production, prev_collections = OfficeBudgetHelper.load_prev_month_production_collection(
                    start_day_of_prev_month, last_day_of_prev_month, office.dental_api_key
                )
            except Exception:
                pass
            else:
                opendental_data[office.pk] = {
                    "adjusted_production": prev_adjusted_production,
                    "collection": prev_collections,
                }
        budgets_to_clone = [office.previous_budget[0] for office in offices if office.previous_budget]
        OfficeBudgetHelper.clone_prev_month_budget(budgets_to_clone, opendental_data)

    @staticmethod
    def load_dental_data(dental_api_key: str, month: Optional[Month] = None):
        if month is None:
            month = Month.from_date(timezone.localdate()) - 1
        return OfficeBudgetHelper.load_prev_month_production_collection(
            month.first_day(), month.last_day(), dental_api_key
        )

    @staticmethod
    def load_prev_month_production_collection(day1, day2, api_key):
        with open("query/production.sql") as f:
            product_query = f.read()
        query = product_query.format(day_from=day1, day_to=day2)
        od_client = OpenDentalClient(api_key)
        json_production, status = od_client.query(query)
        if status != HTTP_200_OK:
            return 0, 0
        adjusted_production, collections = (
            json_production[0]["Adjusted_Production"],
            json_production[0]["Collections"],
        )
        return adjusted_production, collections

    @staticmethod
    def get_office_spent_budget_current_month(office):
        current_month = Month.from_date(timezone.localtime().date())
        first_day_current_month = datetime(current_month.year, current_month.month, 1)
        orders = Order.objects.filter(office=office, order_date__gte=first_day_current_month).aggregate(
            total_amount=Sum("total_amount")
        )
        total_order_amount = orders["total_amount"] if orders["total_amount"] else 0.0
        return total_order_amount

    @staticmethod
    def adjust_spends(office_id: int, month: Month, spends: BudgetwiseSpend):
        subaccounts = {s.slug: s for s in Subaccount.objects.filter(budget__office_id=office_id, budget__month=month)}
        for slug, spend in spends.items():
            subaccount = subaccounts.get(slug)
            if not subaccount:
                logger.warning("Missing subaccount for office %s month %s slug %s", office_id, month, slug)
            else:
                subaccount.spend = F("spend") + spend
        Subaccount.objects.bulk_update(subaccounts.values(), fields=("spend",))

    @staticmethod
    def get_or_create_budget(office_id: int, month: Optional[Month] = None):
        if month is None:
            month = Month.from_date(timezone.localdate())
        budget = Budget.objects.filter(office_id=office_id, month=month).first()
        if budget:
            return budget
        most_recent_budget = Budget.objects.filter(office_id=office_id, month__lt=month).order_by("-month").first()
        if not most_recent_budget:
            # Create if we couldn't find any
            budget = Budget.objects.create(
                office_id=office_id,
                month=month,
                adjusted_production=0,
                collection=0,
            )
            subaccounts_to_create = [
                {
                    "slug": slug,
                    "percentage": DEFAULT_PERCENTAGE_MAPPING[slug],
                    "vendors": [],
                    "name": slug.capitalize(),
                }
                for slug in ("dental", "office", "miscellaneous")
            ]
        else:
            budget = Budget.objects.create(
                office_id=office_id, month=month, basis=most_recent_budget.basis, adjusted_production=0, collection=0
            )
            subaccounts_to_create = [
                {
                    "slug": slug,
                    "percentage": percentage,
                    "name": name,
                    "vendors": vendors,
                }
                for slug, percentage, name, vendors in Subaccount.objects.filter(
                    budget=most_recent_budget
                ).values_list("slug", "percentage", "name", "vendors")
            ]
        for subaccount_data in subaccounts_to_create:
            Subaccount.objects.create(budget=budget, **subaccount_data)
        return budget

    @staticmethod
    def get_or_create_subaccount(budget, slug):
        subaccount = Subaccount.objects.filter(budget=budget, slug=slug).first()
        if subaccount:
            return subaccount
        subaccount = (
            Subaccount.objects.filter(budget__office_id=budget.office_id, slug=slug)
            .annotate(
                from_past=Case(
                    When(budget__month__lt=budget.month, then=Value(1)), default=Value(0), output_field=IntegerField()
                ),
                month_diff=ExpressionWrapper(F("budget__month") - budget.month._date, output_field=DurationField()),
                abs_month_diff=Greatest(F("month_diff"), -F("month_diff"), output_field=DurationField()),
            )
            .order_by("-from_past", "-abs_month_diff")
            .first()
        )
        if subaccount:
            data = {"vendors": subaccount.vendors, "name": subaccount.name, "percentage": subaccount.percentage}
        else:
            data = {
                "vendors": [],
                "name": slug.capitalize(),
                "percentage": DEFAULT_PERCENTAGE_MAPPING.get(slug, DEFAULT_PERCENTAGE),
            }
        subaccount = Subaccount.objects.create(budget=budget, slug=slug, spend=0, **data)
        return subaccount

    @staticmethod
    def get_slug_mapping(budget_id: int):
        result = {
            **{slug: "dental" for slug in ALL_VENDORS},
            **{slug: "office" for slug in DEFAULT_FRONT_OFFICE_BUDGET_VENDORS},
        }
        for s in Subaccount.objects.filter(budget=budget_id):
            for vendor_slug in s.vendors:
                result[vendor_slug] = s.slug
        return result

    @staticmethod
    def remove_subaccount(subaccount: Subaccount, substitute_slug: str):
        if subaccount.slug in BUILTIN_BUDGET_SLUGS:
            return
        slug = subaccount.slug
        Subaccount.objects.filter(budget__office=subaccount.budget.office_id, slug=subaccount.slug).delete()
        VendorOrderProduct.objects.filter(
            budget_spend_type=slug,
        ).update(budget_spend_type=substitute_slug)

    @staticmethod
    def get_default_budget_type_by_vendor(slug: str):
        return "office" if slug in DEFAULT_FRONT_OFFICE_BUDGET_VENDORS else "dental"


class ShippingHelper:
    @staticmethod
    def get_connected_vendor_ids(office: Union[int, str, Office]) -> List[str]:
        if not isinstance(office, Office):
            office = Office.objects.get(id=office)

        return office.connected_vendors.values_list("vendor_id", flat=True)

    @staticmethod
    def import_shipping_options_from_json(file_path, vendor_slug, office_id=None):
        if not office_id:
            office_ids = Office.objects.all().values_list("pk", flat=True).distinct()
            for office_id in office_ids:
                ShippingHelper.import_shipping_options_for_one_office(
                    file_path=file_path, vendor_slug=vendor_slug, office_id=office_id
                )
        else:
            ShippingHelper.import_shipping_options_for_one_office(
                file_path=file_path, vendor_slug=vendor_slug, office_id=office_id
            )

    @staticmethod
    def import_shipping_options_for_one_office(file_path, vendor_slug, office_id):
        with open(file_path, "r") as file:
            data = json.loads(file.read())
        vendor = VendorModel.objects.get(slug=vendor_slug)
        office = Office.objects.get(id=office_id)

        connected_vendor_ids = ShippingHelper.get_connected_vendor_ids(office_id)
        if vendor.id in connected_vendor_ids:
            default_shipping_method = data["default_shipping_method"]
            shipping_options = data["shipping_options"]
            default_shipping_option: dict = {}

            shipping_options_to_be_created = []
            office_vendor = OfficeVendorModel.objects.filter(office=office, vendor=vendor).first()
            office_vendor.shipping_options.clear()

            for option in shipping_options:
                price = shipping_options[option]["shipping"].strip("$")
                price = price if price else None
                name = shipping_options[option]["shipping_method"]
                value = shipping_options[option].get("shipping_value", "")
                if name == default_shipping_method:
                    default_shipping_option = shipping_options[option]
                print("Creating new shopping option")
                shipping_options_to_be_created.append(ShippingMethodModel(name=name, price=price, value=value))

            shipping_options_objs = bulk_create(model_class=ShippingMethodModel, objs=shipping_options_to_be_created)
            print(f"{vendor}: {len(shipping_options_to_be_created)} shipping options created")

            default_shipping_option_obj = [
                o for o in shipping_options_objs if o.name == default_shipping_option["shipping_method"]
            ][0]
            office_vendor.default_shipping_option = default_shipping_option_obj
            for obj in shipping_options_objs:
                office_vendor.shipping_options.add(obj)
            office_vendor.save()

    @staticmethod
    def find_subaccount(office_id, vendor_slug, month: Optional[Month] = None) -> Optional[Subaccount]:
        if month is None:
            month = Month.from_date(timezone.localdate())
        return (
            Subaccount.objects.filter(budget__office_id=office_id, budget__month=month)
            .filter(Q(vendors__contains=vendor_slug) | Q(slug=get_vendor_budget_slug(vendor_slug)))
            .order_by(OrderBy("slug", nulls_first=True))
            .first()
        )
