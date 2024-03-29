import datetime

from django.contrib.postgres.search import SearchVectorField
from django.db.models import Exists, OuterRef, Q
from django.db.models.expressions import RawSQL
from django_filters import rest_framework as filters

from apps.common.choices import OrderStatus, ProductStatus
from apps.common.utils import get_date_range

from .models import OfficeProduct, Order, Product, VendorOrder, VendorOrderProduct


class OrderFilter(filters.FilterSet):
    start_date = filters.DateFilter(field_name="order_date", lookup_expr="gte")
    end_date = filters.DateFilter(field_name="order_date", lookup_expr="lte")
    vendor = filters.CharFilter(field_name="vendor_orders__vendor__slug", lookup_expr="iexact")

    class Meta:
        model = Order
        fields = ["start_date", "end_date", "status", "vendor"]


class VendorOrderFilter(filters.FilterSet):
    ids = filters.CharFilter(method="filter_by_ids")
    start_date = filters.DateFilter(field_name="order_date", lookup_expr="gte")
    end_date = filters.DateFilter(field_name="order_date", lookup_expr="lte")
    budget_type = filters.CharFilter(method="filter_by_budget_type")
    date_range = filters.CharFilter(method="filter_by_range")
    status = filters.CharFilter(method="filter_by_status")
    disable_approval = filters.BooleanFilter(method="filter_by_disable_approval")
    q = filters.CharFilter(method="filter_orders")

    class Meta:
        model = VendorOrder
        fields = ["status", "start_date", "end_date"]

    @staticmethod
    def filter_by_disable_approval(queryset, name, value):
        return queryset.exclude(status=OrderStatus.PENDING_APPROVAL)

    @staticmethod
    def filter_by_status(queryset, name, value):
        if value == ProductStatus.BACK_ORDERED.value:
            return queryset.filter(
                Exists(VendorOrderProduct.objects.filter(vendor_order=OuterRef("pk"), status=value))
            )
        return queryset.filter(**{name: value})

    @staticmethod
    def filter_by_ids(queryset, name, value):
        ids = value.split(",")
        q = Q(id__in=ids)

        return queryset.filter(q)

    @staticmethod
    def filter_by_budget_type(queryset, name, value):
        q = Q()
        if value == "dental":
            q = ~Q(vendor__slug="amazon")
        elif value == "office":
            q = Q(vendor__slug="amazon")

        return queryset.filter(q)

    @staticmethod
    def filter_by_range(queryset, name, value):
        start_end_date = get_date_range(value)
        if start_end_date:
            q = Q(order_date__gte=start_end_date[0]) & Q(order_date__lte=start_end_date[1])
            return queryset.filter(q)
        else:
            return queryset

    @staticmethod
    def filter_orders(queryset, name, value):
        q = (
            Q(products__name__icontains=value)
            | Q(products__category__name__icontains=value)
            | Q(vendor__name__icontains=value)
            | Q(nickname__icontains=value)
        )
        try:
            value = datetime.datetime.strptime(value, "%m/%d/%y").date()
            q |= Q(order_date=value)
        except (TypeError, ValueError):
            pass
        return queryset.filter(q).distinct()


class VendorOrderProductFilter(filters.FilterSet):
    product_name = filters.CharFilter(field_name="product__name", lookup_expr="icontains")
    category = filters.CharFilter(field_name="product__category__slug", lookup_expr="exact")
    start_date = filters.DateFilter(field_name="vendor_order__order_date", lookup_expr="gte")
    end_date = filters.DateFilter(field_name="vendor_order__order_date", lookup_expr="lte")
    budget_type = filters.CharFilter(field_name="budget_spend_type")

    class Meta:
        model = VendorOrderProduct
        fields = ["product_name", "category", "budget_type", "start_date", "end_date"]


class ProductFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_product")

    class Meta:
        model = Product
        fields = ["q"]

    def filter_product(self, queryset, name, value):
        q = Q(product_id=value) | Q(name__icontains=value) | Q(tags__keyword__iexact=value)
        return queryset.filter(q).distinct()


class ProductV2Filter(filters.FilterSet):
    price_from = filters.NumberFilter(method="filter_by_price_range", lookup_expr="gte")
    price_to = filters.NumberFilter(method="filter_by_price_range", lookup_expr="lte")

    @staticmethod
    def filter_by_price_range(queryset, name, value):
        query = Q(child__isnull=False)

        if name == "price_from":
            query |= Q(child__isnull=True) & Q(product_price__gte=value)
        else:
            query |= Q(child__isnull=True) & Q(product_price__lte=value)
        queryset = queryset.filter(query)

        return queryset

    # def filter_by_name(self, queryset, name, value):
    #     product_id_value = value.replace("-", "")
    #     return queryset.filter(
    #         Q(name__search=value)
    #         | Q(product_id__icontains=product_id_value)
    #         | Q(product_id__icontains=value)
    #         | Q(child__product_id__icontains=product_id_value)
    #         | Q(child__product_id__icontains=value)
    #     ).distinct()


class OfficeProductFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_product")
    inventory = filters.BooleanFilter(field_name="is_inventory")
    favorite = filters.BooleanFilter(field_name="is_favorite")
    category = filters.CharFilter(field_name="office_product_category__slug")
    vendors = filters.CharFilter(method="filter_by_vendors")

    class Meta:
        model = OfficeProduct
        fields = ["q", "inventory", "favorite"]

    def filter_product(self, queryset, name, value):
        products = Product.objects.filter(parent__in=Product.objects.search(value))
        office_product_ids = (
            OfficeProduct.objects.annotate(nn_vector=RawSQL("nn_vector", params=[], output_field=SearchVectorField()))
            .filter(nn_vector=value)
            .values_list("product_id", flat=True)
        )
        office_nickname_products = Product.objects.filter(id__in=office_product_ids)
        products = products | office_nickname_products
        product_ids = products.values_list("id", flat=True)
        return queryset.filter(product_id__in=product_ids)
        # q = (
        #     Q(product__product_id=value)
        #     | Q(product__name__icontains=value)
        #     | Q(product__tags__keyword__iexact=value)
        #     | Q(product__child__product_id=value)
        #     | Q(product__child__name__icontains=value)
        #     | Q(product__child__tags__keyword__iexact=value)
        # )
        # return queryset.filter(q).distinct()

    def filter_by_vendors(self, queryset, name, value):
        vendors = value.split(",")
        if vendors:
            return queryset.filter(vendor__slug__in=vendors)
        return queryset

class OfficeProductFilterForUnlinkedVendors(filters.FilterSet):
    q = filters.CharFilter(method="filter_product")
    favorite = filters.BooleanFilter(field_name="is_favorite")
    category = filters.CharFilter(field_name="office_product_category__slug")

    class Meta:
        model = OfficeProduct
        fields = ["q", "favorite"]

    def filter_product(self, queryset, name, value):
        products = Product.objects.filter(parent__in=Product.objects.search(value))
        office_product_ids = (
            OfficeProduct.objects.annotate(nn_vector=RawSQL("nn_vector", params=[], output_field=SearchVectorField()))
            .filter(nn_vector=value)
            .values_list("product_id", flat=True)
        )
        office_nickname_products = Product.objects.filter(id__in=office_product_ids)
        products = products | office_nickname_products
        product_ids = products.values_list("id", flat=True)
        return queryset.filter(product_id__in=product_ids)
        