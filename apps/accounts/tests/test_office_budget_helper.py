import decimal
from datetime import timedelta
from typing import Dict
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from unittest_parametrize import ParametrizedTestCase, param, parametrize

from apps.accounts.factories import (
    OpenDentalKeyFactory,
    SubaccountFactory,
    VendorFactory,
)
from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import BUILTIN_BUDGET_SLUGS, Budget, Subaccount
from apps.accounts.tests.utils import (
    CloneOverrides,
    Overrides,
    _make_company,
    escape_to_varname,
    last_year_months,
)
from apps.common.choices import ProductStatus
from apps.common.month import Month
from apps.orders.factories import (
    OrderFactory,
    VendorOrderFactory,
    VendorOrderProductFactory,
)
from apps.orders.models import VendorOrderProduct
from config.constants import ALL_VENDORS

clone_test_variants = parametrize(
    "overrides",
    (
        ("none",),
        ("next_month",),
        ("two_months",),
        ("new_basis",),
    ),
)


update_spend_variants = parametrize(
    "slug,delta",
    [
        param(slug, delta, id=escape_to_varname(f"{slug}_{delta}"))
        for slug in ("dental", "office")
        for delta in (1, -1)
    ],
)

move_spend_category_variants = parametrize(
    "src,dst,amount,expected",
    [
        param(src, dst, amount, expected, id=escape_to_varname(f"{src}_to_{dst}_{amount}"))
        for src, dst, amount, expected in (
            ("dental", "dental", 10, False),
            ("dental", "vendor-net_32", 10, True),
            ("dental", "office", 10, True),
        )
    ],
)

clone_prev_month_budget_variants = parametrize(
    "dental_api_data",
    [
        param(None, id="none"),
        param(
            {
                0: {"adjusted_production": 10, "collection": -10},
                1: {"adjusted_production": 20, "collection": -20},
                2: {"adjusted_production": 30, "collection": -30},
            },
            id="set",
        ),
    ],
)


class OfficeHelperTestCase(ParametrizedTestCase, TestCase):
    @classmethod
    def setUpTestData(cls):
        budget_months = list(last_year_months())
        cls.companies = [_make_company(budget_months) for _ in range(3)]

    @clone_test_variants
    def test_clone(self, overrides):
        cs = self.companies[0]
        overrides_result: Overrides = getattr(CloneOverrides, overrides)(cs)
        last_month = cs.months[-1]
        budget = cs.budgets[last_month]
        new_budget = OfficeBudgetHelper.clone_budget(budget, overrides=overrides_result.overrides)
        expected = overrides_result.expected
        assert new_budget.month == expected.month
        if expected.basis:
            assert new_budget.basis == expected.basis
        old_subaccounts: Dict[str, Subaccount] = {s.slug: s for s in budget.subaccounts.all()}
        new_subaccounts: Dict[str, Subaccount] = {s.slug: s for s in new_budget.subaccounts.all()}
        for slug in ("dental", "office"):
            old_subaccount = old_subaccounts[slug]
            new_subaccount = new_subaccounts[slug]
            assert old_subaccount.percentage == new_subaccount.percentage
            assert new_subaccount.spend == 0
            expected_data = overrides_result.expected.data
            if not expected_data:
                continue
            for k, v in expected_data.items():
                assert getattr(new_subaccount, k) == v

    @update_spend_variants
    def test_update_spend(self, slug, delta):
        cs = self.companies[0]
        month = cs.months[-1]
        spend_before = Budget.objects.get(pk=cs.budgets[month].pk).subaccounts.get(slug=slug).spend
        OfficeBudgetHelper.update_spend(cs.office, month, delta, slug)
        spend_after = Budget.objects.get(pk=cs.budgets[month].pk).subaccounts.get(slug=slug).spend
        assert spend_after - spend_before == delta

    @move_spend_category_variants
    def test_move_spend_category(self, src, dst, amount, expected):
        cs = self.companies[0]
        month = cs.months[-1]
        src_before = Subaccount.objects.filter(budget__office=cs.office, budget__month=month, slug=src).first()
        dst_before = Subaccount.objects.filter(budget__office=cs.office, budget__month=month, slug=dst).first()
        result = OfficeBudgetHelper.move_spend_category(cs.office, month, amount, src, dst)
        assert result == expected
        src_after = Subaccount.objects.filter(budget__office=cs.office, budget__month=month, slug=src).first()
        dst_after = Subaccount.objects.filter(budget__office=cs.office, budget__month=month, slug=dst).first()
        if not expected:
            assert src_before.spend == src_after.spend
            if dst_before:
                assert dst_before.spend == dst_after.spend
        else:
            assert src_before and src_before.spend == src_after.spend + amount
            if dst_before:
                assert dst_before.spend == dst_after.spend - amount

    @clone_prev_month_budget_variants
    def test_clone_prev_month_budget(self, dental_api_data):
        budgets = [cs.budgets[cs.months[-1]] for cs in self.companies]
        month = self.companies[0].months[-1]

        new_dental_api_data = {}
        for budget in budgets:
            new_dental_api_data[budget.office_id] = {
                "adjusted_production": budget.adjusted_production,
                "collection": budget.collection,
            }
        if dental_api_data:
            for idx, deltas in dental_api_data.items():
                cs = self.companies[idx]
                budget = cs.budgets[cs.months[-1]]
                new_dental_api_data[budget.office_id]["adjusted_production"] += deltas["adjusted_production"]
                new_dental_api_data[budget.office_id]["collection"] += deltas["collection"]

        OfficeBudgetHelper.clone_prev_month_budget(budgets, dental_api_data=new_dental_api_data)

        next_month = month + 1
        for budget in Budget.objects.filter(month=next_month):
            assert budget.collection == new_dental_api_data[budget.office_id]["collection"]
            assert budget.adjusted_production == new_dental_api_data[budget.office_id]["adjusted_production"]

    def test_update_office_budgets(self):
        current_month = self.companies[0].months[-1]
        for cs in self.companies:
            cs.office.dental_api = OpenDentalKeyFactory()
            cs.office.save()
            budget = cs.budgets.pop(current_month)
            budget.subaccounts.all().delete()
            budget.delete()
        adjusted_production = 100
        collection = 200
        with patch.object(
            OfficeBudgetHelper, "load_prev_month_production_collection", return_value=(adjusted_production, collection)
        ):
            OfficeBudgetHelper.update_office_budgets()
        budgets = list(Budget.objects.filter(month=current_month))
        assert len(budgets) == 3
        for b in budgets:
            assert b.adjusted_production == adjusted_production
            assert b.collection == collection

    def test_get_or_create_budget_existing(self):
        cs = self.companies[0]
        budget = OfficeBudgetHelper.get_or_create_budget(cs.office.id, cs.months[-1])
        assert budget.id == cs.budgets[cs.months[-1]].id

    def test_get_or_create_budget_new(self):
        cs = self.companies[0]
        last_budget = cs.budgets[cs.months[-1]]
        SubaccountFactory(budget=last_budget, slug="my-budget", name="My Budget", vendors=[], percentage=5)
        SubaccountFactory(
            budget=last_budget, slug="my-budget-2", name="My Budget 2", vendors=["henry_schein", "darby"], percentage=3
        )
        budget = OfficeBudgetHelper.get_or_create_budget(cs.office.id, cs.months[-1] + 1)
        subaccounts = list(budget.subaccounts.all())
        assert {s.slug for s in subaccounts} == {*BUILTIN_BUDGET_SLUGS, "my-budget", "my-budget-2"}
        assert {s.name for s in subaccounts} == {
            *map(str.capitalize, BUILTIN_BUDGET_SLUGS),
            "My Budget",
            "My Budget 2",
        }
        assert {tuple(s.vendors) for s in subaccounts} == {(), (), (), (), ("henry_schein", "darby")}

    def test_get_or_create_budget_not_existing(self):
        cs = _make_company([])
        month = Month.from_date(timezone.localdate())
        budget = OfficeBudgetHelper.get_or_create_budget(cs.office.id, month)
        assert budget
        subaccounts = list(budget.subaccounts.all())
        slugs = set(BUILTIN_BUDGET_SLUGS) - {"miscellaneous"}
        assert {s.slug for s in subaccounts} == slugs
        assert {s.name for s in subaccounts} == set(map(str.capitalize, slugs))
        assert all(s.vendors == [] for s in subaccounts)

    def test_get_slug_mapping_no_custom(self):
        cs = self.companies[0]
        budget = OfficeBudgetHelper.get_or_create_budget(cs.office.id, cs.months[-1])
        mapping = OfficeBudgetHelper.get_slug_mapping(budget)
        assert mapping == {**{slug: "dental" for slug in ALL_VENDORS}, "amazon": "office"}

    def test_get_slug_mapping_custom(self):
        cs = self.companies[0]
        last_budget = cs.budgets[cs.months[-1]]
        SubaccountFactory(budget=last_budget, slug="my-budget", name="My Budget", vendors=["benco"], percentage=5)
        SubaccountFactory(
            budget=last_budget, slug="my-budget-2", name="My Budget 2", vendors=["henry_schein", "darby"], percentage=3
        )
        budget = OfficeBudgetHelper.get_or_create_budget(cs.office.id, cs.months[-1] + 1)
        mapping = OfficeBudgetHelper.get_slug_mapping(budget)
        assert mapping == {
            **{slug: "dental" for slug in ALL_VENDORS},
            "amazon": "office",
            "benco": "my-budget",
            "henry_schein": "my-budget-2",
            "darby": "my-budget-2",
        }

    def test_remove_subaccounts(self):
        cs = self.companies[0]
        last_budget = cs.budgets[cs.months[-1]]
        subaccount = SubaccountFactory(
            budget=last_budget, slug="my-budget", name="My Budget", vendors=["benco"], percentage=5
        )
        vendor = VendorFactory(slug="benco", name="Benco")
        order_date = cs.months[-1].first_day() + timedelta(days=10)
        order = OrderFactory(
            office=cs.office,
            order_date=order_date,
            total_items=1,
            total_amount=decimal.Decimal(100),
        )
        vendor_order = VendorOrderFactory(
            vendor=vendor, order=order, total_amount=100, total_items=1, order_date=order_date
        )
        vop = VendorOrderProductFactory(
            vendor_order=vendor_order,
            unit_price=100,
            status=ProductStatus.DELIVERED,
            budget_spend_type=subaccount.slug,
        )
        OfficeBudgetHelper.remove_subaccount(subaccount, substitute_slug="dental")
        vop = VendorOrderProduct.objects.get(pk=vop.pk)
        assert vop.budget_spend_type == "dental"
