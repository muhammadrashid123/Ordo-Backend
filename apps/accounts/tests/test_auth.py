from django.utils.dateparse import parse_datetime
from faker import Faker
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from apps.accounts.factories import CompanyFactory, CompanyMemberFactory, UserFactory
from apps.accounts.models import User
from apps.accounts.tests.helpers import ensure_jwt_payload_correct

fake = Faker()


def same(x):
    return x


fields_to_check_user = {
    "id": same,
    "avatar": same,
    "last_login": same,
    "username": same,
    "first_name": same,
    "last_name": same,
    "email": same,
    "is_active": same,
    "date_joined": parse_datetime,
    "role": same,
}


fields_to_check_company = {
    "id": same,
    "created_at": parse_datetime,
    "updated_at": parse_datetime,
    "name": same,
    "slug": same,
    "on_boarding_step": same,
    "is_active": same,
    "billing_together": same,
}


class UserSignupTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_password = fake.pystr()
        cls.user: User = UserFactory()
        cls.company = CompanyFactory()
        cls.company_member = CompanyMemberFactory(user=cls.user, company=cls.company)
        cls.user.set_password(cls.user_password)
        cls.user.save()

    def ensure_payload_correct(self, profile):
        for k, func in fields_to_check_user.items():
            assert func(profile[k]) == getattr(self.user, k)

        company = profile.pop("company")

        for k, func in fields_to_check_company.items():
            assert func(company[k]) == getattr(self.company, k)

        offices = company.pop("offices")
        assert len(offices) == 1

    def test_auth(self):
        resp = self.client.post(
            reverse("login"),
            data={"username": self.user.username, "password": self.user_password},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        profile = data["data"]["profile"]
        self.ensure_payload_correct(profile)
        token = data["data"]["token"]
        ensure_jwt_payload_correct(token, self.user)

    def test_verify_token(self):
        resp = self.client.post(
            reverse("login"),
            data={"username": self.user.username, "password": self.user_password},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        token = data["data"]["token"]
        resp = self.client.post(
            reverse("verify-token"),
            data={"token": token},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        profile = data["data"]["profile"]
        self.ensure_payload_correct(profile)
