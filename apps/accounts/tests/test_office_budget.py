import datetime
import decimal
from typing import List, Literal
from unittest.mock import patch

from django.utils import timezone
from faker import Faker
from pydantic import BaseModel, validator
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.factories import (
    BudgetFactory,
    CompanyFactory,
    CompanyMemberFactory,
    OfficeFactory,
    SubaccountFactory,
    UserFactory,
    VendorFactory,
)
from apps.accounts.models import BasisType, Budget, CompanyMember, Subaccount, User
from apps.accounts.tests.utils import (
    VersionedAPIClient,
    _make_company,
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

fake = Faker()


class RemainingBudget(BaseModel):
    dental: float
    office: float


BudgetType = Literal["production", "collection"]


class SubaccountOutput(BaseModel):
    id: int
    slug: str
    spend: decimal.Decimal
    percentage: decimal.Decimal
    name: str
    vendors: List[str]


class ChartBudget(BaseModel):
    month: Month
    dental_budget: decimal.Decimal
    dental_spend: decimal.Decimal
    office_budget: decimal.Decimal
    office_spend: decimal.Decimal

    @validator("month", pre=True)
    def normalize_month(cls, value):
        return Month.from_string(value)

    class Config:
        arbitrary_types_allowed = True


class ChartBudgetV2(BaseModel):
    month: Month
    subaccounts: List[SubaccountOutput]

    @validator("month", pre=True)
    def normalize_month(cls, value):
        return Month.from_string(value)

    class Config:
        arbitrary_types_allowed = True


class BudgetOutputV2(BaseModel):
    id: int
    office: int
    basis: int
    month: datetime.date
    adjusted_production: decimal.Decimal
    collection: decimal.Decimal
    subaccounts: List[SubaccountOutput]


class SingleOfficeBudgetV2TestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.company_member_user = UserFactory()
        cls.company_member = CompanyMemberFactory(company=cls.company, office=cls.office, user=cls.company_member_user)
        cls.office_budget = BudgetFactory(office=cls.office)
        cls.api_client = VersionedAPIClient(version="2.0")
        cls.api_client.force_authenticate(cls.company_member_user)

    def test_company_member(self):
        url = reverse("members-list", kwargs={"company_pk": self.company.pk})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        member_data = data["data"][0]
        office_data = member_data["office"]
        budget = BudgetOutputV2(**office_data["budget"])
        assert budget

    def test_company(self):
        url = reverse("companies-detail", kwargs={"pk": self.company.pk})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        office_data = data["data"]["offices"][0]
        budget = BudgetOutputV2(**office_data["budget"])
        assert budget

    def test_budgets_list(self):
        url = reverse("budgets-list", kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        budget_data = data["data"][0]
        budget = BudgetOutputV2(**budget_data)
        assert budget

    def test_budgets_detail(self):
        url = reverse(
            "budgets-detail",
            kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk, "pk": self.office_budget.pk},
        )
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        budget_data = data["data"]
        budget = BudgetOutputV2(**budget_data)
        assert budget

    def test_update_budget(self):
        url = reverse(
            "budgets-detail",
            kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk, "pk": self.office_budget.pk},
        )
        db_subaccount = {s.slug: s for s in self.office_budget.subaccounts.all()}
        update_data = {
            "basis": BasisType.COLLECTION,
            "collection": decimal.Decimal("152319.74"),
            "subaccounts": [
                {
                    "id": db_subaccount["dental"].id,
                    "percentage": decimal.Decimal("4.5"),
                },
                {
                    "id": db_subaccount["office"].id,
                    "percentage": decimal.Decimal("0.9"),
                },
                {
                    "id": db_subaccount["miscellaneous"].id,
                    "percentage": decimal.Decimal("100"),
                },
            ],
        }
        resp = self.api_client.put(url, data=update_data, format="json")
        assert resp
        url = reverse(
            "budgets-detail",
            kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk, "pk": self.office_budget.pk},
        )

        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        budget_data = data["data"]
        budget = BudgetOutputV2(**budget_data)
        for field_name, value in update_data.items():
            if field_name == "subaccounts":
                sdata = {o.id: o for o in budget.subaccounts}
                udata = {o["id"]: o for o in update_data["subaccounts"]}
                assert sdata.keys() == udata.keys()
                for k in sdata.keys():
                    assert sdata[k].percentage == udata[k]["percentage"]
            else:
                assert getattr(budget, field_name) == update_data[field_name]

    def test_get_current_month_budget(self):
        url = reverse("budgets-stats", kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        budget_data = data["data"]
        budget = BudgetOutputV2(**budget_data)
        assert budget

    def test_user_self(self):
        url = reverse("users-detail", kwargs={"pk": "me"})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        user_data = data["data"]
        company_data = user_data["company"]
        office_data = company_data["offices"][0]
        budget_data = office_data["budget"]
        budget = BudgetOutputV2(**budget_data)
        assert budget


class TestSubaccounts(APITestCase):
    @classmethod
    def setUpTestData(cls):
        budget_months = list(last_year_months())
        cls.companies = [_make_company(budget_months) for _ in range(3)]
        cls.user = UserFactory()
        cls.company_member = CompanyMemberFactory(
            company=cls.companies[0].company, user=cls.user, office=cls.companies[0].office
        )
        cls.api = APIClient()
        cls.api.force_authenticate(cls.user)

    def test_remove_subaccounts(self):
        cs = self.companies[0]
        last_budget = cs.budgets[cs.months[-1]]
        subaccount = SubaccountFactory(
            budget=last_budget, slug="my-budget", name="My Budget", vendors=["benco"], percentage=5
        )
        vendor = VendorFactory(slug="benco", name="Benco")
        order_date = cs.months[-1].first_day() + datetime.timedelta(days=10)
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
        resp = self.api.post(
            reverse(
                "subaccounts-remove",
                kwargs={"company_pk": cs.company.pk, "office_pk": cs.office.pk, "pk": subaccount.pk},
            ),
            data={"substitute_slug": "dental"},
            format="json",
        )
        assert resp.status_code == 204
        vop = VendorOrderProduct.objects.get(pk=vop.pk)
        assert vop.budget_spend_type == "dental"


class ChartDataTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.company_member_user = UserFactory()
        cls.company_member = CompanyMemberFactory(company=cls.company, office=cls.office, user=cls.company_member_user)
        for month in last_year_months():
            cls.office_budget = BudgetFactory(office=cls.office, month=month)
        cls.api_client = VersionedAPIClient(version="2.0")
        cls.api_client.force_authenticate(cls.company_member_user)

    def test_chart_data(self):
        url = reverse("budgets-get-chart-data", kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk})
        resp = self.api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        for budget_data in data["data"]:
            budget = ChartBudgetV2(**budget_data)
            assert budget


class BudgetCreateTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.company_member_user = UserFactory()
        cls.company_member = CompanyMemberFactory(company=cls.company, office=cls.office, user=cls.company_member_user)
        cls.api_client = VersionedAPIClient(version="2.0")
        cls.api_client.force_authenticate(cls.company_member_user)

    def test_budget_create(self):
        url = reverse("budgets-list", kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk})
        data = {
            "basis": BasisType.COLLECTION,
            "adjusted_production": 100000,
            "collection": 50000,
            "subaccounts": [
                {"slug": "dental", "percentage": 5, "name": "Dental"},
                {"slug": "office", "percentage": 1, "name": "Office"},
                {"slug": "miscellaneous", "name": "Miscellaneous"},
            ],
        }
        resp = self.api_client.post(url, data, format="json")
        assert resp.status_code == 201
        month = Month.from_date(timezone.localdate())
        budget = Budget.objects.filter(office=self.office, month=month).first()
        assert budget.basis == BasisType.COLLECTION
        assert budget.adjusted_production == 100000
        assert budget.collection == 50000
        subaccounts = {s.slug: s for s in budget.subaccounts.all()}
        assert len(subaccounts) == 3
        assert subaccounts["dental"].percentage == 5
        assert subaccounts["office"].percentage == 1
        assert subaccounts["miscellaneous"].percentage == 0

    def test_budget_create2(self):
        url = reverse("budgets-list", kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk})
        data = {
            "basis": BasisType.COLLECTION,
            "adjusted_production": 100000,
            "collection": 50000,
            "subaccounts": [
                {"slug": "dental", "percentage": 5, "name": "Dental", "vendors": []},
                {"slug": "office", "percentage": 1, "name": "Office", "vendors": []},
                {"slug": "miscellaneous", "name": "Miscellaneous", "vendors": []},
                {"slug": "henry", "name": "Henry", "vendors": []},
            ],
        }
        resp = self.api_client.post(url, data, format="json")
        assert resp.status_code == 201
        month = Month.from_date(timezone.localdate())
        budget = Budget.objects.filter(office=self.office, month=month).first()
        subaccounts = {s.slug: s for s in budget.subaccounts.all()}
        assert len(subaccounts) == 4


class BudgetUpdateTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.company_member_user = UserFactory()
        cls.company_member = CompanyMemberFactory(company=cls.company, office=cls.office, user=cls.company_member_user)
        cls.office_budget = BudgetFactory(office=cls.office)
        cls.api_client = VersionedAPIClient(version="2.0")
        cls.api_client.force_authenticate(cls.company_member_user)

    def _get_existing_data(self) -> dict:
        return {
            "basis": self.office_budget.basis,
            "adjusted_production": self.office_budget.adjusted_production,
            "collection": self.office_budget.collection,
            "subaccounts": [
                {"id": s.id, "slug": s.slug, "percentage": s.percentage, "name": s.name}
                for s in self.office_budget.subaccounts.all()
            ],
        }

    def get_url(self):
        return reverse(
            "budgets-detail",
            kwargs={"company_pk": self.company.pk, "office_pk": self.office.pk, "pk": self.office_budget.pk},
        )

    def test_updating_nothing(self):
        resp = self.api_client.put(self.get_url(), data=self._get_existing_data(), format="json")
        assert resp.status_code == 200

    def test_add_one_more_budget_no_vendors(self):
        data = self._get_existing_data()
        data["subaccounts"].append({"percentage": 5, "name": "Mike's budget"})
        resp = self.api_client.put(self.get_url(), data=data, format="json")
        assert resp.status_code == 200
        subaccounts = list(Subaccount.objects.filter(budget=self.office_budget))
        assert len(subaccounts) == 4
        new_subaccount = Subaccount.objects.filter(budget=self.office_budget, slug="mike-s-budget").first()
        assert new_subaccount.percentage == 5
        assert new_subaccount.name == "Mike's budget"

    def test_add_one_more_budget_with_vendors(self):
        data = self._get_existing_data()
        data["subaccounts"].append({"percentage": 5, "name": "Mike's budget", "vendors": ["henry_schein"]})
        resp = self.api_client.put(self.get_url(), data=data, format="json")
        assert resp.status_code == 200
        subaccounts = list(Subaccount.objects.filter(budget=self.office_budget))
        assert len(subaccounts) == 4
        new_subaccount = Subaccount.objects.filter(budget=self.office_budget, slug="mike-s-budget").first()
        assert new_subaccount.percentage == 5
        assert new_subaccount.name == "Mike's budget"
        assert new_subaccount.vendors == ["henry_schein"]

    def test_add_one_more_budget_with_intersecting_vendors(self):
        data = self._get_existing_data()
        data["subaccounts"] = [
            *data["subaccounts"],
            {"percentage": 5, "name": "Mike's budget", "vendors": ["henry_schein"]},
            {"percentage": 5, "name": "Special budget", "vendors": ["henry_schein"]},
        ]
        resp = self.api_client.put(self.get_url(), data=data, format="json")
        assert resp.status_code == 400
        subaccounts = list(Subaccount.objects.filter(budget=self.office_budget))
        assert len(subaccounts) == 3

    def test_update_remove_builtin(self):
        slug_to_test = "dental"
        assert Subaccount.objects.filter(budget=self.office_budget).count() == 3
        data = self._get_existing_data()
        data["subaccounts"] = [o for o in data["subaccounts"] if o["slug"] != slug_to_test]
        resp = self.api_client.put(self.get_url(), data=data, format="json")
        assert resp.status_code == 200
        assert Subaccount.objects.filter(budget=self.office_budget).count() == 3
        assert Subaccount.objects.filter(budget=self.office_budget, slug=slug_to_test).exists()

    def test_update_slug(self):
        data = self._get_existing_data()
        existing_slugs = set(Subaccount.objects.filter(budget=self.office_budget).values_list("slug", flat=True))
        data["subaccounts"] = [{**o, "slug": "{}-new".format(o["slug"])} for o in data["subaccounts"]]
        resp = self.api_client.put(self.get_url(), data=data, format="json")
        assert resp.status_code == 200
        new_slugs = set(Subaccount.objects.filter(budget=self.office_budget).values_list("slug", flat=True))
        assert existing_slugs == new_slugs


class TestUserSignUpTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company)
        cls.company_member = CompanyMemberFactory(
            company=cls.company,
            office=cls.office,
            invite_status=CompanyMember.InviteStatus.INVITE_SENT,
            user=None,
        )
        for month in last_year_months():
            cls.office_budget = BudgetFactory(office=cls.office, month=month)
        cls.api_client = VersionedAPIClient(version="2.0")

    def test_user_signup_with_token(self):
        url = reverse("signup")
        first_name = fake.first_name()
        last_name = fake.last_name()
        with patch("apps.accounts.tasks.send_welcome_email.run") as mock:
            resp = self.api_client.post(
                url,
                data={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": self.company_member.email,
                    "password": fake.password(),
                    "company_name": self.company.name,
                    "token": self.company_member.token,
                },
                format="json",
            )
        assert resp.status_code == 200
        assert mock.called_once_with(user_id=User.objects.get(email=self.company_member.email).pk)
        data = resp.json()
        budget_data = data["data"]["company"]["offices"][0]["budget"]
        budget = BudgetOutputV2(**budget_data)
        assert budget

    def test_user_signup_without_token(self):
        url = reverse("signup")
        first_name = fake.first_name()
        last_name = fake.last_name()
        email = f"{first_name}.{last_name}@example.com"
        with patch("apps.accounts.tasks.send_welcome_email.run") as mock:
            resp = self.api_client.post(
                url,
                data={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "password": fake.password(),
                    "company_name": fake.company(),
                },
                format="json",
            )
        assert resp.status_code == 200
        assert mock.called_once_with(user_id=User.objects.get(email=email).pk)
        data = resp.json()
        offices = data["data"]["company"]["offices"]
        assert len(offices) == 0
