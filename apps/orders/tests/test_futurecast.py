import datetime
import math
from unittest import skip

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.factories import (
    CompanyFactory,
    CompanyMemberFactory,
    OfficeFactory,
    OfficeVendorFactory,
    UserFactory,
)
from apps.accounts.models import User
from apps.orders.factories import (
    ProcedureCategoryLinkFactory,
    ProcedureCodeFactory,
    ProcedureFactory,
)


# TODO: write OpenDental mock client in order to be able
#       to test it
class FutureCastAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.company = CompanyFactory()
        cls.company_office = OfficeFactory(company=cls.company)
        cls.office = OfficeFactory(company=cls.company)
        cls.office_vendor = OfficeVendorFactory(office=cls.office)
        cls.admin = UserFactory(role=User.Role.ADMIN)
        cls.api_client = APIClient()
        cls.api_client.force_authenticate(cls.admin)
        CompanyMemberFactory(company=cls.company, user=cls.admin, email=cls.admin.email)
        # Summary category
        cls.category1 = ProcedureCategoryLinkFactory(
            summary_slug="Whitening", linked_slugs=["whitening"], category_order=2, is_favorite=True
        )
        cls.category2 = ProcedureCategoryLinkFactory(
            summary_slug="Bone Graft",
            linked_slugs=["surgical-supplies", "anesthetics"],
            category_order=4,
            is_favorite=False,
        )
        # Procedure Code for summary category category1
        cls.proccode1 = ProcedureCodeFactory(
            proccode="D9972", category="testcategory1", summary_category=cls.category1
        )
        cls.proccode2 = ProcedureCodeFactory(
            proccode="D9973", category="testcategory2", summary_category=cls.category1
        )
        # Procedure Code for summary category category2
        cls.proccode3 = ProcedureCodeFactory(
            proccode="D4263", category="testcategory2", summary_category=cls.category2
        )
        # Available procedure history for thisMonth
        proc1 = ProcedureFactory(
            start_date=datetime.date.today().replace(day=1),
            count=5,
            procedurecode=cls.proccode1,
            office=cls.office,
            # type="month",
        )
        proc2 = ProcedureFactory(
            start_date=datetime.date.today().replace(day=1),
            count=3,
            procedurecode=cls.proccode2,
            office=cls.office,
            # type="month",
        )
        proc3 = ProcedureFactory(
            start_date=datetime.date.today().replace(day=1),
            count=3,
            procedurecode=cls.proccode3,
            office=cls.office,
            # type="month",
        )

        # Unavailable procedure history for thisMonth, but available for last 3 months
        proc4 = ProcedureFactory(
            start_date=datetime.date.today().replace(day=1) - relativedelta(months=1),
            count=13,
            procedurecode=cls.proccode1,
            office=cls.office,
            # type="month",
        )
        proc5 = ProcedureFactory(
            start_date=datetime.date.today().replace(day=1) - relativedelta(months=2),
            count=20,
            procedurecode=cls.proccode2,
            office=cls.office,
            # type="month",
        )
        cls.expected_order_count1 = proc1.count + proc2.count
        cls.expected_order_count2 = proc3.count
        cls.expected_order_avg_count1 = math.floor((proc4.count + proc5.count) / 3)
        cls.expected_order_avg_count2 = 0

    @skip
    def test_summary_category(self):
        link = reverse(
            "procedures-summary-category", kwargs={"company_pk": self.company.id, "office_pk": self.office.id}
        )
        link = f"{link}?type=month&date_range=thisMonth"
        response = self.api_client.get(link)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.data

        self.assertEqual(len(result), 2)  # Number of summary category
        r1, r2 = result
        self.assertEqual(r1["order"], 2)
        self.assertEqual(r1["slug"], self.category1.summary_slug)
        self.assertEqual(r1["is_favorite"], True)
        self.assertEqual(r1["count"], self.expected_order_count1)
        self.assertEqual(r1["avg_count"], self.expected_order_avg_count1)
        self.assertEqual(r2["order"], 4)
        self.assertEqual(r2["slug"], self.category2.summary_slug)
        self.assertEqual(r2["is_favorite"], False)
        self.assertEqual(r2["count"], self.expected_order_count2)
        self.assertEqual(r2["avg_count"], self.expected_order_avg_count2)

    @skip
    def test_summary_report(self):
        self.client.force_authenticate(self.admin)
        link = reverse(
            "procedures-summary-detail", kwargs={"company_pk": self.company.id, "office_pk": self.office.id}
        )
        link = f"{link}?date_range=thisWeek&from=2023-01-30&to=2023-02-05&summary_category=Whitening"
        response = self.client.get(link)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
