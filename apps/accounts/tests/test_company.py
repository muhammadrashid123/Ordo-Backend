from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts import factories as f
from apps.accounts.models import User


class CompanyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = f.CompanyFactory()
        cls.company_office_1 = f.OfficeFactory(company=cls.company)
        cls.company_office_2 = f.OfficeFactory(company=cls.company)
        cls.company_admin = f.UserFactory(role=User.Role.ADMIN)
        cls.company_user = f.UserFactory(role=User.Role.USER)

        cls.firm = f.CompanyFactory()
        cls.firm_office = f.OfficeFactory(company=cls.firm)
        cls.firm_admin = f.UserFactory(role=User.Role.ADMIN)
        cls.firm_user = f.UserFactory(role=User.Role.USER)

        f.CompanyMemberFactory(company=cls.company, user=cls.company_admin, email=cls.company_admin.email)
        f.CompanyMemberFactory(company=cls.company, user=cls.company_user, email=cls.company_user.email)
        f.CompanyMemberFactory(company=cls.firm, user=cls.firm_admin, email=cls.firm_admin.email)
        f.CompanyMemberFactory(company=cls.firm, user=cls.firm_user, email=cls.firm_user.email)

    def _check_edit_permission(self, *, method, link, data=None):
        """check create, update, delete permission"""

        def make_call(user=None):
            if user:
                self.client.force_authenticate(user)
            if method == "put":
                return self.client.put(link, data)
            elif method == "delete":
                return self.client.delete(link)
            elif method == "post":
                return self.client.post(link, data)

        # unauthorized user
        response = make_call()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # company admin
        response = make_call(self.company_admin)
        if method == "put":
            expected_status = status.HTTP_200_OK
        elif method == "post":
            expected_status = status.HTTP_201_CREATED
        else:
            expected_status = status.HTTP_204_NO_CONTENT
        self.assertEqual(response.status_code, expected_status)

        # company user
        response = make_call(self.company_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        if method != "delete":
            # firm admin
            response = make_call(self.firm_admin)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

            response = make_call(self.firm_user)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def _check_view_permission(self, *, method, link):
        """check get, list permission"""
        # unauthorized user
        response = self.client.get(link)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        expected_status = status.HTTP_200_OK if method == "get" else status.HTTP_405_METHOD_NOT_ALLOWED

        # company admin
        self.client.force_authenticate(self.company_admin)
        response = self.client.get(link)
        self.assertEqual(response.status_code, expected_status)

        # company user
        self.client.force_authenticate(self.company_user)
        response = self.client.get(link)
        self.assertEqual(response.status_code, expected_status)

        expected_status = status.HTTP_403_FORBIDDEN if method == "get" else status.HTTP_405_METHOD_NOT_ALLOWED
        # firm admin
        self.client.force_authenticate(self.firm_admin)
        response = self.client.get(link)
        self.assertEqual(response.status_code, expected_status)

        # firm user
        self.client.force_authenticate(self.firm_admin)
        response = self.client.get(link)
        self.assertEqual(response.status_code, expected_status)

    def test_company_get_permission(self):
        self._check_view_permission(
            method="get",
            link=reverse("companies-detail", kwargs={"pk": self.company.id}),
        )

    def test_company_list_permission(self):
        self._check_view_permission(
            method="list",
            link=reverse("companies-list"),
        )

    def test_company_create_permission(self):
        pass

    def test_company_update_permission(self):
        data = {"name": "updated company name"}
        self._check_edit_permission(
            method="put",
            link=reverse("companies-detail", kwargs={"pk": self.company.id}),
            data=data,
        )

    def test_company_delete_permission(self):
        self._check_edit_permission(
            method="delete",
            link=reverse("companies-detail", kwargs={"pk": self.company.id}),
        )

    def test_office_get_permission(self):
        self._check_view_permission(
            method="get",
            link=reverse("offices-detail", kwargs={"company_pk": self.company.id, "pk": self.company_office_1.id}),
        )

    def test_office_create_permission(self):
        data = {"name": "updated office name"}
        self._check_edit_permission(
            method="put",
            link=reverse("offices-detail", kwargs={"company_pk": self.company.id, "pk": self.company_office_1.id}),
            data=data,
        )

    def test_office_update_permission(self):
        data = {"name": "updated office name"}
        self._check_edit_permission(
            method="put",
            link=reverse("offices-detail", kwargs={"company_pk": self.company.id, "pk": self.company_office_1.id}),
            data=data,
        )

    def test_office_delete_permission(self):
        self._check_edit_permission(
            method="delete",
            link=reverse("offices-detail", kwargs={"company_pk": self.company.id, "pk": self.company_office_1.id}),
        )
