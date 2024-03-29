from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient, APITestCase
from unittest_parametrize import ParametrizedTestCase, parametrize

from apps.accounts.factories import CompanyFactory, UserFactory
from apps.accounts.models import Company

FIELDS = (
    "offices_added",
    "subscribed",
    "vendors_linked",
    "budget_set",
    "team_invited",
)

patch_test_variants = parametrize(
    "field_name",
    [(fname,) for fname in FIELDS],
)


class OnboardingStatusTest(ParametrizedTestCase, APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.company_creator_user = UserFactory()
        cls.company: Company = CompanyFactory(creator=cls.company_creator_user)
        cls.user_api = APIClient()
        cls.user_api.force_authenticate(cls.user)
        cls.creator_api = APIClient()
        cls.creator_api.force_authenticate(cls.company_creator_user)

    def test_onboarding_status_get(self):
        resp = self.user_api.get(reverse("companies-onboarding-status", kwargs={"pk": self.company.pk}))
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_onboarding_status_get_creator(self):
        resp = self.creator_api.get(reverse("companies-onboarding-status", kwargs={"pk": self.company.pk}))
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["data"]
        assert data["company"] == self.company.pk

    @patch_test_variants
    def test_onboarding_update(self, field_name):
        self.creator_api.patch(
            reverse("companies-onboarding-status", kwargs={"pk": self.company.pk}), data={field_name: True}
        )
        status = self.company.onboarding_status
        status.refresh_from_db()
        assert getattr(status, field_name)
