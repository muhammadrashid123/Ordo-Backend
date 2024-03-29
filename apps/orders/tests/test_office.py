from unittest.mock import patch

from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.factories import (
    CompanyFactory,
    CompanyMemberFactory,
    OfficeFactory,
    OpenDentalKeyFactory,
    UserFactory,
)
from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import BasisType


class OfficeTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.open_dental_key = OpenDentalKeyFactory()
        cls.company = CompanyFactory()
        cls.office = OfficeFactory(company=cls.company, dental_api=None)
        cls.user = UserFactory()
        cls.member = CompanyMemberFactory(company=cls.company, user=cls.user, office=cls.office)
        cls.api = APIClient()
        cls.api.force_authenticate(cls.user)

    def test_set_dental_api(self):
        production, collection = 10000, 15000
        with patch(
            "apps.accounts.helper.OfficeBudgetHelper.load_dental_data", return_value=(production, collection)
        ) as load_dental_data_mock:
            resp = self.api.post(
                reverse("offices-set-dental-api", kwargs={"company_pk": self.company.pk, "pk": self.office.pk}),
                data={"dental_key": self.open_dental_key.key, "budget_type": BasisType.COLLECTION.value},
            )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert load_dental_data_mock.called
        budget = OfficeBudgetHelper.get_or_create_budget(self.office.pk)
        assert budget.adjusted_production == production
        assert budget.collection == collection
