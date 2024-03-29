from django.urls import reverse
from django.utils import timezone
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.factories import CompanyMemberFactory, UserFactory
from apps.accounts.models import CompanyMember, User
from apps.accounts.tests.helpers import ensure_jwt_payload_correct
from apps.common import messages

fake = Faker()


SIGNUP_DATA = {
    "company_name": "Company Name",
    "first_name": "First",
    "last_name": "Last",
    "email": "test@test.com",
    "password": "test",
}


class UserSignupTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.invited_member = CompanyMemberFactory(
            token=fake.pystr(),
            email=fake.email(),
        )
        cls.existing_user = UserFactory()

    def _ensure_company_data_correct(self, response, company_member):
        data = response.json()["data"]
        company_data = data["company"]
        assert company_data["id"] == company_member.company_id

    def test_signup_invited(self):
        response = self.client.post(
            reverse("signup"),
            data={**SIGNUP_DATA, "token": self.invited_member.token, "email": self.invited_member.email},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        user = User.objects.filter(
            username=self.invited_member.email,
            email=self.invited_member.email,
            first_name=SIGNUP_DATA["first_name"],
            last_name=SIGNUP_DATA["last_name"],
        ).first()
        assert user is not None
        company_member = CompanyMember.objects.get(id=self.invited_member.pk)
        assert company_member.user == user
        assert company_member.invite_status == CompanyMember.InviteStatus.INVITE_APPROVED
        # Make sure the member was created very recently
        assert (timezone.localtime() - company_member.date_joined).total_seconds() < 2

        data = response.json()["data"]
        assert data.keys() == {"token", "company"}
        self._ensure_company_data_correct(response, company_member)
        ensure_jwt_payload_correct(data["token"], user)

    def test_signup_new(self):
        response = self.client.post(
            reverse("signup"),
            data={**SIGNUP_DATA},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        user = User.objects.filter(
            username=SIGNUP_DATA["email"],
            email=SIGNUP_DATA["email"],
            first_name=SIGNUP_DATA["first_name"],
            last_name=SIGNUP_DATA["last_name"],
        ).first()
        assert user is not None
        company_member = CompanyMember.objects.filter(user=user).first()
        assert company_member.invite_status == CompanyMember.InviteStatus.INVITE_APPROVED
        # Make sure the member was created very recently
        assert (timezone.localtime() - company_member.date_joined).total_seconds() < 2

        data = response.json()["data"]
        assert data.keys() == {"token", "company"}
        self._ensure_company_data_correct(response, company_member)
        ensure_jwt_payload_correct(data["token"], user)

    def test_signup_invited_wrong_token(self):
        response = self.client.post(
            reverse("signup"), data={**SIGNUP_DATA, "token": fake.pystr(), "email": self.invited_member.email}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_existing_user_should_fail(self):
        response = self.client.post(reverse("signup"), data={**SIGNUP_DATA, "email": self.existing_user.email})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        message = response.json()["message"]
        assert message == messages.SIGNUP_DUPLICATE_EMAIL

    def test_create_account_missing_data(self):
        for k, _ in SIGNUP_DATA.items():
            data = {k1: v for k1, v in SIGNUP_DATA.items() if k1 != k}
            response = self.client.post(reverse("signup"), data=data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, data)
