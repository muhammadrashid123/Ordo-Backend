import csv

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.db.models import Q
from django.http import HttpResponse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from nested_admin.nested import NestedModelAdmin, NestedTabularInline

from apps.common.admins import AdminDynamicPaginationMixin, ReadOnlyAdminMixin
from apps.common.utils import CUSTOM_DATE_FILTER, get_date_range

from . import models as m


# This is a comment
class ExportCsvMixin:
    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename={}.csv".format(meta)
        writer = csv.writer(response)

        writer.writerow(field_names)
        for obj in queryset:
            writer.writerow([getattr(obj, field) for field in field_names])

        return response

    export_as_csv.short_description = "Export Selected"


class VendorOrderProductInline(ReadOnlyAdminMixin, NestedTabularInline):
    model = m.VendorOrderProduct
    fields = (
        "product",
        "unit_price",
        "quantity",
        "total_price",
        "status",
        "vendor_status",
        "tracking_link",
    )
    readonly_fields = (
        "product",
        "unit_price",
        "quantity",
        "total_price",
        "vendor_status",
        "tracking_link",
    )

    def total_price(self, obj):
        return obj.quantity * obj.unit_price

    # def track(self, obj):
    #     return mark_safe(f"<a href='{obj.tracking_link}'> Track </a>")


class VendorOrderInline(ReadOnlyAdminMixin, NestedTabularInline):
    model = m.VendorOrder
    fk_name = "order"
    fields = readonly_fields = (
        "vendor",
        "invoice",
        "vendor_order_reference",
        "order_date",
        "total_amount",
        "total_items",
        "nickname",
        "currency",
        "status",
    )
    inlines = (VendorOrderProductInline,)

    def invoice(self, obj):
        return mark_safe(f"<a href='{obj.invoice_link}'> {obj.vendor_order_id} </a>")


class OrderVendorFilter(SimpleListFilter):
    title = "Vendor"
    parameter_name = "vendors"

    def lookups(self, request, model_admin):
        return m.Vendor.objects.values_list("slug", "name")

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        return queryset.filter(vendor_orders__vendor__slug=value)


class OrderDateFilter(SimpleListFilter):
    title = "Date Range"
    parameter_name = "date_range"

    def lookups(self, request, model_admin):
        return CUSTOM_DATE_FILTER

    def queryset(self, request, queryset):
        value = self.value()
        date_range = get_date_range(value)

        if not date_range:
            return queryset
        return queryset.filter(Q(order_date__gte=date_range[0], order_date__lte=date_range[1]))


@admin.register(m.Order)
class OrderAdmin(AdminDynamicPaginationMixin, NestedModelAdmin):
    list_display = ("id", "company", "office", "vendors", "total_amount", "order_date", "order_type", "status")
    search_fields = (
        "vendor_orders__vendor__name",
        "office__name",
        "office__company__name",
        "order_type",
        "status",
        "vendor_orders__nickname",
    )
    readonly_fields = (
        "office",
        "created_by",
        "order_date",
        "total_items",
        "total_amount",
    )
    list_filter = (
        "status",
        OrderVendorFilter,
        OrderDateFilter,
    )
    inlines = (VendorOrderInline,)

    @admin.display(description="Company")
    def company(self, obj):
        return obj.office.company

    @admin.display(description="Vendors")
    def vendors(self, objs):
        return ", ".join([vendor_order.vendor.name for vendor_order in objs.vendor_orders.all()])

    @admin.display(description="Order Total")
    def total_amount(self, objs):
        return objs.total_amount

    company.admin_order_field = "office__company"


@admin.register(m.VendorOrder)
class VendorOrderAdmin(AdminDynamicPaginationMixin, NestedModelAdmin):
    list_display = (
        "vendor",
        "invoice",
        "vendor_order_reference",
        "order_date",
        "total_amount",
        "total_items",
        "nickname",
        "currency",
        "status",
    )
    search_fields = ("vendor_order_id",)
    inlines = (VendorOrderProductInline,)

    def invoice(self, obj):
        return format_html("<a href='{}'> {} </a>", obj.invoice_link, obj.vendor_order_id)


class ProductPriceFilter(SimpleListFilter):
    title = "Price Range"
    parameter_name = "price"

    def lookups(self, request, model_admin):
        return ("_100", "0 - 100"), ("100_200", "100 - 200"), ("200_300", "200 - 300"), ("300_", "300 +")

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        if value == "_100":
            return queryset.filter(price__lte=100)
        elif value == "100_200":
            return queryset.filter(Q(price__gt=100) & Q(price__lte=200))
        elif value == "200_300":
            return queryset.filter(Q(price__gt=200) & Q(price__lte=300))
        else:
            return queryset.filter(price__gt=300)


@admin.register(m.ProductCategory)
class ProductCategoryAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    list_display = ("__str__", "name", "parent")


@admin.register(m.OfficeProductCategory)
class OfficeProductCategoryAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    list_display = ("id", "office", "name", "slug", "predefined")
    search_fields = (
        "office__name",
        "name",
        "slug",
    )


class ProductImageInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = m.ProductImage
    readonly_fields = (
        "image_preview",
        "image",
    )

    def image_preview(self, obj):
        return mark_safe("<img src='{}'  width='30' height='30' />".format(obj.image))

    image_preview.short_description = "Preview"


@admin.register(m.Product)
class ProductAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "product_thumb",
        "product_id",
        "name",
        "vendor",
        "category",
        "get_url",
    )
    search_fields = (
        "product_id",
        "name",
        "tags__keyword",
    )
    list_filter = (
        "vendor",
        "category",
    )
    exclude = ("parent",)
    inlines = (ProductImageInline,)

    @admin.display(description="url")
    def get_url(self, obj):
        return mark_safe(f"<a target='_blank' href={obj.url}>Link</a>")

    @admin.display(description="Image")
    def product_thumb(self, obj):
        image = obj.images.first()
        if image:
            return mark_safe("<img src='{}'  width='30' height='30' />".format(image.image))
        else:
            return "No Image Found"


@admin.register(m.Keyword)
class KeywordAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    search_fields = ("keyword",)


@admin.register(m.OfficeKeyword)
class OfficeKeywordAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    list_display = (
        "keyword",
        "office",
        "vendor",
        "task_status",
    )
    list_filter = ("task_status", "vendor")
    search_fields = ("keyword__keyword",)


@admin.register(m.OfficeProduct)
class OfficeProductAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    actions = ["export_as_csv"]
    list_display = (
        "id",
        "office",
        "product_id",
        "product_name",
        "product_vendor",
        "office_product_category",
        "product_category",
        "price",
        "nickname",
        "is_favorite",
        "is_inventory",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "product__product_id",
        "product__name",
        "product__tags__keyword",
        "office__name",
    )

    list_filter = (
        "is_inventory",
        "is_favorite",
        "product__vendor",
    )

    @admin.display(description="Product ID")
    def product_id(self, obj):
        return obj.product.product_id

    @admin.display(description="Product Name")
    def product_name(self, obj):
        return obj.product.name

    @admin.display(description="Vendor")
    def product_vendor(self, obj):
        return obj.product.vendor

    @admin.display(description="Product Category")
    def product_category(self, obj):
        return obj.product.category

    def export_as_csv(self, request, queryset):
        field_names = ["Product Name", "Product ID", "Vendor", "price", "last_order_date", "last_order_price"]

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=inventory.csv"
        writer = csv.writer(response)

        writer.writerow(field_names)
        queryset = (
            queryset.select_related("vendor", "product")
            .filter(product__vendor__isnull=False)
            .values(
                "product__name",
                "product__product_id",
                "product__vendor__name",
                "price",
                "last_order_date",
                "last_order_price",
            )
        )
        for obj in queryset:
            writer.writerow(
                [
                    obj["product__name"],
                    obj["product__product_id"],
                    obj["product__vendor__name"],
                    obj["price"],
                    obj["last_order_date"],
                    obj["last_order_price"],
                ]
            )

        return response

    export_as_csv.short_description = "Export Selected"


@admin.register(m.PriceAge)
class PriceAgeAdmin(admin.ModelAdmin):
    list_display = ("office_name", "vendor_slug", "age_group", "count")
    list_display_links = []
    list_filter = ["office_name", "vendor_slug", "age_group"]
    readonly_fields = ("id", "office_name", "vendor_slug", "age_group", "count")

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs):
        return False
