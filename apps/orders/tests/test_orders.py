import datetime
import uuid
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.factories import (
    CompanyFactory,
    CompanyMemberFactory,
    OfficeFactory,
    OfficeVendorFactory,
    SubscriptionFactory,
    UserFactory,
    VendorFactory,
)
from apps.accounts.models import Office, User, Vendor
from apps.common.choices import OrderStatus, ProductStatus
from apps.orders.factories import (
    OrderFactory,
    OrderProductFactory,
    ProductFactory,
    VendorOrderFactory,
)
from apps.orders.models import Order, Product, VendorOrder, VendorOrderProduct


class DashboardAPIPermissionTests(APITestCase):
    def setUp(self) -> None:
        self.company = CompanyFactory()
        self.company_office_1 = OfficeFactory(company=self.company)
        self.company_office_2 = OfficeFactory(company=self.company)
        self.company_admin = UserFactory(role=User.Role.ADMIN)
        self.company_user = UserFactory(role=User.Role.USER)

        self.firm = CompanyFactory()
        self.firm_office = OfficeFactory(company=self.firm)
        self.firm_admin = UserFactory(role=User.Role.ADMIN)
        self.firm_user = UserFactory(role=User.Role.USER)

        CompanyMemberFactory(company=self.company, user=self.company_admin, email=self.company_admin.email)
        CompanyMemberFactory(company=self.company, user=self.company_user, email=self.company_user.email)
        CompanyMemberFactory(company=self.firm, user=self.firm_admin, email=self.firm_admin.email)
        CompanyMemberFactory(company=self.firm, user=self.firm_user, email=self.firm_user.email)

    def _check_get_spend_permission(self, method, link):
        def make_call(user=None):
            self.client.force_authenticate(user)
            if method == "get":
                return self.client.get(link)
            elif method == "put":
                return self.client.put(link, {})
            elif method == "delete":
                return self.client.delete(link)
            elif method == "post":
                return self.client.post(link, {})

        response = make_call()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        expected_status = status.HTTP_200_OK if method == "get" else status.HTTP_405_METHOD_NOT_ALLOWED

        # company admin
        response = make_call(self.company_admin)
        self.assertEqual(response.status_code, expected_status)

        # company user
        response = make_call(self.company_user)
        self.assertEqual(response.status_code, expected_status)

        expected_status = status.HTTP_403_FORBIDDEN if method == "get" else status.HTTP_405_METHOD_NOT_ALLOWED
        # firm admin
        response = make_call(self.firm_admin)
        self.assertEqual(response.status_code, expected_status)

        # firm user
        response = make_call(self.firm_user)
        self.assertEqual(response.status_code, expected_status)

    def test_get_spend_company(self):
        link = reverse("company-spending", kwargs={"company_pk": self.company.id})
        self._check_get_spend_permission(method="get", link=f"{link}?by=vendor")
        self._check_get_spend_permission(method="get", link=f"{link}?by=month")

    def test_get_spend_office(self):
        link = reverse("office-spending", kwargs={"office_pk": self.company_office_1.id})
        self._check_get_spend_permission(method="get", link=f"{link}?by=vendor")
        self._check_get_spend_permission(method="get", link=f"{link}?by=month")


class CompanyOfficeSpendTests(APITestCase):
    @classmethod
    def _create_orders(cls, product: Product, office: Office, vendor: Vendor):
        for i in range(12):
            order_date = datetime.date.today() - relativedelta(months=i)
            order = OrderFactory(
                office=office,
                total_amount=product.price,
                # currency="USD",
                order_date=order_date,
                status="complete",
            )
            vendor_order = VendorOrderFactory(vendor=vendor, order=order, total_amount=product.price)
            OrderProductFactory(
                vendor_order=vendor_order,
                product=product,
                quantity=1,
                unit_price=product.price,
                status="complete",
            )

    @classmethod
    def setUpTestData(cls) -> None:
        cls.company = CompanyFactory()
        cls.vendor1_name = "HenrySchien"
        cls.vendor2_name = "Net 32"
        cls.vendor1 = VendorFactory(name=cls.vendor1_name, slug="henry_schein", url="https://www.henryschein.com/")
        cls.vendor2 = VendorFactory(name=cls.vendor2_name, slug="net_32", url="https://www.net32.com/")
        cls.office1 = OfficeFactory(company=cls.company)
        cls.office2 = OfficeFactory(company=cls.company)
        cls.admin = UserFactory(role=User.Role.ADMIN)
        CompanyMemberFactory(company=cls.company, user=cls.admin, email=cls.admin.email)

        cls.product1_price = Decimal("10.00")
        cls.product2_price = Decimal("100.00")
        cls.product1 = ProductFactory(
            vendor=cls.vendor1,
            price=cls.product1_price,
        )
        cls.product2 = ProductFactory(
            vendor=cls.vendor2,
            price=cls.product2_price,
        )
        cls.office1_vendor1 = OfficeVendorFactory(office=cls.office1, vendor=cls.vendor1)
        cls.office1_vendor2 = OfficeVendorFactory(office=cls.office2, vendor=cls.vendor2)

        # office1 vendors
        cls._create_orders(cls.product1, cls.office1, cls.vendor1)

        # office2 vendors
        cls._create_orders(cls.product2, cls.office2, cls.vendor2)

    def test_company_get_spending_by_vendor(self):
        link = reverse("company-spending", kwargs={"company_pk": self.company.id})
        link = f"{link}?by=vendor"
        self.client.force_authenticate(self.admin)
        response = self.client.get(link)
        result = sorted(response.data, key=lambda x: x["total_amount"])
        for res, price, name in zip(
            result, [self.product1_price, self.product2_price], [self.vendor1_name, self.vendor2_name]
        ):
            self.assertEqual(Decimal(res["total_amount"]), price * 12)
            self.assertEqual(res["vendor"]["name"], name)

    def test_company_get_spending_by_month(self):
        # TODO: there is instability in this test case
        link = reverse("company-spending", kwargs={"company_pk": self.company.id})
        link = f"{link}?by=month"
        self.client.force_authenticate(self.admin)
        response = self.client.get(link)
        result = response.data
        for res in result:
            self.assertEqual(Decimal(res["total_amount"]), self.product1_price + self.product2_price)

    def test_office_get_spending_by_vendor(self):
        self.client.force_authenticate(self.admin)
        link = reverse("office-spending", kwargs={"office_pk": self.office1.id})
        link = f"{link}?by=vendor"
        response = self.client.get(link)
        response_data = response.data[0]
        self.assertEqual(Decimal(response_data["total_amount"]), self.product1_price * 12)
        self.assertEqual(response_data["vendor"]["name"], self.vendor1_name)

        link = reverse("office-spending", kwargs={"office_pk": self.office2.id})
        link = f"{link}?by=vendor"
        response = self.client.get(link)
        response_data = response.data[0]
        self.assertEqual(Decimal(response_data["total_amount"]), self.product2_price * 12)
        self.assertEqual(response_data["vendor"]["name"], self.vendor2_name)

    def test_office_get_spending_by_month(self):
        self.client.force_authenticate(self.admin)
        link = reverse("office-spending", kwargs={"office_pk": self.office1.id})
        link = f"{link}?by=month"
        response = self.client.get(link)
        for res in response.data:
            self.assertEqual(Decimal(res["total_amount"]), self.product1_price)

        link = reverse("office-spending", kwargs={"office_pk": self.office2.id})
        link = f"{link}?by=month"
        response = self.client.get(link)
        for res in response.data:
            self.assertEqual(Decimal(res["total_amount"]), self.product2_price)


class VendorOrderTests(APITestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.company = CompanyFactory()
        cls.vendor1_name = "HenrySchien"
        cls.vendor2_name = "Net 32"
        cls.vendor1 = VendorFactory(name=cls.vendor1_name, slug="henry_schein", url="https://www.henryschein.com/")
        cls.vendor2 = VendorFactory(name=cls.vendor2_name, slug="net_32", url="https://www.net32.com/")
        cls.office = OfficeFactory(company=cls.company)
        SubscriptionFactory(office=cls.office, start_on="2022-02-03")
        cls.admin = UserFactory(role=User.Role.ADMIN)
        CompanyMemberFactory(company=cls.company, user=cls.admin, email=cls.admin.email)
        cls.api_client = APIClient()
        cls.api_client.force_authenticate(cls.admin)
        cls.product1_price = Decimal("10.00")
        cls.product2_price = Decimal("100.00")
        cls.product3_price = Decimal("1000.00")
        cls.product4_price = Decimal("1500.00")
        cls.product1 = ProductFactory(
            vendor=cls.vendor1,
            price=cls.product1_price,
        )
        cls.product2 = ProductFactory(
            vendor=cls.vendor2,
            price=cls.product2_price,
        )
        cls.product3 = ProductFactory(
            vendor=cls.vendor1,
            price=cls.product3_price,
        )
        cls.product4 = ProductFactory(
            vendor=cls.vendor1,
            price=cls.product4_price,
        )
        cls.office_vendor1 = OfficeVendorFactory(office=cls.office, vendor=cls.vendor1)
        cls.office_vendor2 = OfficeVendorFactory(office=cls.office, vendor=cls.vendor2)

        random_order_id = f"{uuid.uuid4()}"
        order_date = datetime.date.today() - relativedelta(days=5)
        cls.order = OrderFactory(
            office=cls.office,
            total_amount=cls.product1_price,
            total_items=1,
            order_date=order_date,
            status=OrderStatus.PENDING_APPROVAL,
        )
        cls.vendor_order = VendorOrderFactory(
            order=cls.order,
            vendor=cls.vendor1,
            vendor_order_id=random_order_id,
            total_amount=cls.product1_price,
            total_items=1,
            order_date=order_date,
            status=OrderStatus.PENDING_APPROVAL,
        )
        cls.order_product = OrderProductFactory(
            vendor_order=cls.vendor_order,
            product=cls.product1,
            quantity=1,
            unit_price=cls.product1_price,
            status=ProductStatus.PENDING_APPROVAL,
        )

    def test_pending_approval_count(self):
        url = reverse(
            "vendor-orders-pending-stats", kwargs={"company_pk": self.company.id, "office_pk": self.office.id}
        )
        response = self.api_client.get(url)
        assert response.status_code == 200
        data = response.json()["data"]
        assert "count" in data
        assert data["count"] == 1

    def test_add_order_product(self):
        print("test_add_order_product")
        link = reverse(
            "orders-add-item-to-vendororder",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order.id},
        )
        response = self.api_client.post(link, {"product": self.product3.id, "quantity": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)
        self.assertEqual(self.vendor_order.total_items, 2)
        self.assertEqual(self.vendor_order.total_amount, self.product1_price + self.product3_price * 2)
        self.assertEqual(self.order.total_items, 2)
        self.assertEqual(self.order.total_amount, self.product1_price + self.product3_price * 2)

        response = self.api_client.post(link, {"product": self.product2.id, "quantity": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)
        order_product2_id = response.data
        order_product2 = VendorOrderProduct.objects.get(id=order_product2_id)
        vendor_order2 = order_product2.vendor_order
        self.assertEqual(vendor_order2.total_items, 1)
        self.assertEqual(vendor_order2.total_amount, self.product2_price)
        self.assertEqual(self.vendor_order.total_items, 2)
        self.assertEqual(self.vendor_order.total_amount, self.product1_price + self.product3_price * 2)
        self.assertEqual(self.order.total_items, 3)
        self.assertEqual(self.order.total_amount, self.product1_price + self.product3_price * 2 + self.product2_price)

    def test_remove_order_product(self):
        link = reverse(
            "orders-add-item-to-vendororder",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order.id},
        )
        response = self.api_client.post(link, {"product": self.product3.id, "quantity": 2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order_product3_id = response.data
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)

        link = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order_product.id},
        )
        response = self.api_client.delete(link)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)
        self.assertEqual(self.vendor_order.total_items, 1)
        self.assertEqual(self.vendor_order.total_amount, self.product3_price * 2)
        self.assertEqual(self.order.total_items, 1)
        self.assertEqual(self.order.total_amount, self.product3_price * 2)

        link = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": order_product3_id},
        )
        response = self.api_client.delete(link)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vendor_order_count = self.order.vendor_orders.count()
        self.assertEqual(vendor_order_count, 0)

    def test_order_product_change_vendor(self):
        link = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order_product.id},
        )
        new_quantity = 10
        data = {"product": self.product4.id, "quantity": new_quantity}
        response = self.api_client.patch(link, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)

        self.assertEqual(self.order.vendor_orders.count(), 1)
        self.assertEqual(self.vendor_order.total_amount, self.product4_price * new_quantity)
        self.assertEqual(self.vendor_order.total_items, 1)

        link = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order_product.id},
        )
        response = self.api_client.patch(link, {"product": self.product2.id, "quantity": 5})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor2)
        self.assertEqual(self.order.vendor_orders.count(), 1)
        self.assertEqual(self.order.total_amount, self.product2_price * 5)
        self.assertEqual(self.order.total_items, 1)
        self.assertEqual(self.vendor_order.vendor_id, self.vendor2.id)

    def test_order_product_change2(self):
        p2_amount = 9
        p3_amount = 2
        link_add = reverse(
            "orders-add-item-to-vendororder",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order.id},
        )
        response = self.api_client.post(link_add, {"product": self.product3.id, "quantity": p3_amount})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order_product3_id = response.data

        link_change = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": self.order_product.id},
        )
        response = self.api_client.patch(link_change, {"product": self.product2.id, "quantity": p2_amount})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        self.vendor_order = VendorOrder.objects.get(order=self.order, vendor=self.vendor1)
        vendor_order2 = VendorOrder.objects.get(order=self.order, vendor=self.vendor2)

        self.assertEqual(self.order.vendor_orders.count(), 2)
        self.assertEqual(self.order.total_amount, self.product3_price * p3_amount + self.product2_price * p2_amount)
        self.assertEqual(self.order.total_items, 2)
        self.assertEqual(self.vendor_order.total_items, 1)
        self.assertEqual(self.vendor_order.total_amount, self.product3_price * p3_amount)
        self.assertEqual(vendor_order2.total_items, 1)
        self.assertEqual(vendor_order2.total_amount, self.product2_price * p2_amount)

        p2_amount2 = 65
        link_change = reverse(
            "order-products-detail",
            kwargs={"company_pk": self.company.id, "office_pk": self.office.id, "pk": order_product3_id},
        )
        response = self.api_client.patch(link_change, {"product": self.product2.id, "quantity": p2_amount2})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order = Order.objects.get(id=self.order.id)
        vendor_order2 = VendorOrder.objects.get(order=self.order, vendor=self.vendor2)
        order_product2 = VendorOrderProduct.objects.get(vendor_order_id=vendor_order2.id, product_id=self.product2.id)
        self.assertEqual(self.order.total_items, 1)
        self.assertEqual(self.order.total_amount, self.product2_price * (p2_amount + p2_amount2))
        self.assertEqual(vendor_order2.total_items, 1)
        self.assertEqual(vendor_order2.total_amount, self.product2_price * (p2_amount + p2_amount2))
        self.assertEqual(order_product2.quantity, p2_amount + p2_amount2)
