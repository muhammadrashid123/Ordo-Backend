from typing import List

from rest_framework.test import APIClient, APITestCase

from apps.accounts.factories import (
    BudgetFactory,
    CompanyFactory,
    CompanyMemberFactory,
    OfficeFactory,
    UserFactory,
)
from apps.accounts.tests.utils import Budgets, CompanySet, last_year_months
from apps.common.month import Month


class SubaccountTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        budget_months = list(last_year_months())
        cls.company_set: CompanySet = cls._make_company(budget_months)
        cls.user = UserFactory()
        cls.company_member = CompanyMemberFactory(
            company=cls.company_set.company, user=cls.user, office=cls.company_set.office
        )
        cls.api = APIClient()
        cls.api.force_authenticate(cls.user)

    @classmethod
    def _make_company(cls, budget_months: List[Month]) -> CompanySet:
        company = CompanyFactory()
        office = OfficeFactory(company=company)
        budgets: Budgets = {}
        for month in budget_months:
            budgets[month] = BudgetFactory(office=office, month=month)
        return CompanySet(company=company, office=office, budgets=budgets, months=budget_months)
