from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.tests.factories import AdminUserFactory, UserFactory
from apps.audit.models import ProductParentHistory
from apps.orders.factories import ProductFactory
from apps.orders.models import Product


class ProductManagementTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.parent1 = ProductFactory(parent=None)
        cls.parent2 = ProductFactory(parent=None)
        cls.child = ProductFactory(parent=cls.parent1)
        cls.child2 = ProductFactory(parent=cls.parent2)
        cls.orphan = ProductFactory()
        cls.admin = AdminUserFactory()
        cls.api_client = APIClient()
        cls.api_client.force_authenticate(cls.admin)

    def _manage(self, params, client=None):
        if client is None:
            client = self.api_client
        url = reverse("product-manage")
        resp = client.post(url, params)
        return resp

    def test_regular_user_not_allowed(self):
        client = APIClient()
        user = UserFactory()
        client.force_authenticate(user)
        resp = self._manage({"product": self.child.pk}, client=client)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unlink(self):
        resp = self._manage({"product": self.child.pk})
        assert resp.status_code == 204
        c = Product.objects.get(pk=self.child.pk)
        assert c.parent_id is None
        assert ProductParentHistory.objects.count() == 1

    def test_unlink_orphan(self):
        resp = self._manage({"product": self.orphan.pk})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        c = Product.objects.get(pk=self.orphan.pk)
        assert c.parent_id is None
        assert ProductParentHistory.objects.count() == 0

    def test_move(self):
        resp = self._manage({"product": self.child.pk, "new_parent": self.parent2.pk})
        assert resp.status_code == 204
        c = Product.objects.get(pk=self.child.pk)
        assert c.parent_id is self.parent2.pk
        assert ProductParentHistory.objects.count() == 2

    def test_moving_to_same_parent(self):
        resp = self._manage({"product": self.child.pk, "new_parent": self.parent1.pk})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        c = Product.objects.get(pk=self.child.pk)
        assert c.parent_id is self.parent1.pk
        assert ProductParentHistory.objects.count() == 0

    def test_moving_to_child(self):
        resp = self._manage({"product": self.child.pk, "new_parent": self.child2.pk})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        c = Product.objects.get(pk=self.child.pk)
        assert c.parent_id is self.parent1.pk
        assert ProductParentHistory.objects.count() == 0
