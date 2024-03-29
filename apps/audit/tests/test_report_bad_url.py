from faker import Faker
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase, APIClient

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import BadImageUrl

fake = Faker()

class ReportBadUrlTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.api_client = APIClient()
        cls.api_client.force_authenticate(cls.user)

    def test_url_provided_works(self):
        image_url = fake.url()
        resp = self.api_client.post(
            reverse("report-bad-url"),
            data={"image_url": image_url},
            format="json"
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        bad_image_url = BadImageUrl.objects.first()
        assert bad_image_url.image_url == image_url
        assert bad_image_url.user_id == self.user.pk

    def test_missing_url_fails(self):
        resp = self.api_client.post(
            reverse("report-bad-url"),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
