import re
from typing import Dict, Iterator, List, NamedTuple, Optional

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.factories import BudgetFactory, CompanyFactory, OfficeFactory
from apps.accounts.models import BasisType, Budget, Company, Office
from apps.common.month import Month

Budgets = Dict[Month, Budget]


def last_year_months() -> Iterator[Month]:
    this_month = Month.from_date(timezone.now().date())
    start_month = this_month - 11
    current = start_month
    while current <= this_month:
        yield current
        current += 1


def escape_to_varname(s):
    return re.sub(r"\W|^(?=\d)", "_", s)


class VersionedAPIClient(APIClient):
    def __init__(self, enforce_csrf_checks=False, version="1.0", **defaults):
        super().__init__(enforce_csrf_checks, **defaults)
        self.version = version

    def request(self, **kwargs):
        return super().request(HTTP_ACCEPT=f"application/json; version={self.version}", **kwargs)


class CompanySet(NamedTuple):
    company: Company
    office: Office
    budgets: Budgets
    months: List[Month]


def _make_company(budget_months: List[Month]) -> CompanySet:
    company = CompanyFactory()
    office = OfficeFactory(company=company)
    budgets: Budgets = {}
    for month in budget_months:
        budgets[month] = BudgetFactory(office=office, month=month)
    return CompanySet(company=company, office=office, budgets=budgets, months=budget_months)


class OverridesExpect(NamedTuple):
    month: Month
    basis: Optional[BasisType] = None
    data: Optional[dict] = None


class Overrides(NamedTuple):
    overrides: Optional[dict]
    expected: OverridesExpect


class CloneOverrides:
    @staticmethod
    def none(cs: CompanySet):
        return Overrides(overrides=None, expected=OverridesExpect(month=cs.months[-1] + 1))

    @staticmethod
    def next_month(cs: CompanySet):
        return Overrides(overrides={"month": cs.months[-1] + 1}, expected=OverridesExpect(month=cs.months[-1] + 1))

    @staticmethod
    def two_months(cs: CompanySet):
        return Overrides(overrides={"month": cs.months[-1] + 2}, expected=OverridesExpect(month=cs.months[-1] + 2))

    @staticmethod
    def new_basis(cs: CompanySet):
        b = other_basis(cs.budgets[cs.months[-1]].basis)
        return Overrides(overrides={"basis": b}, expected=OverridesExpect(month=cs.months[-1] + 1, basis=b))


def other_basis(b: BasisType) -> BasisType:
    if b == BasisType.PRODUCTION:
        return BasisType.COLLECTION
    return BasisType.PRODUCTION
