import time

from django.contrib.admin.views.main import PAGE_VAR
from django.db.models import Sum
from django.template import Library
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.accounts.models import Company, Office, OpenDentalKey, User, Vendor
from apps.common.choices import OrderStatus, OrderType
from apps.common.helper import CustomTagHelper
from apps.greetings.models import Greetings
from apps.orders.models import Order, Product, VendorOrder
from apps.waitlist.models import WaitList

register = Library()


@register.simple_tag
def paginator_number(cl, i):
    """
    Generate an individual page index link in a paginated list.
    """
    if i == cl.paginator.ELLIPSIS:
        return format_html("{} ", cl.paginator.ELLIPSIS)
    elif i == cl.page_num:
        return format_html('<li class="page-item active"><a class="page-link">{}</a></li> ', i)
    else:
        return format_html(
            '<li class="page-item"><a class="page-link" href="{}"{}>{}</a></li> ',
            cl.get_query_string({PAGE_VAR: i}),
            mark_safe(' class="end"' if i == cl.paginator.num_pages else ""),
            i,
        )


@register.simple_tag
def edit_link_for_result(cld, result, index):
    try:
        url = cld.url_for_result(result[index])
    except NoReverseMatch:
        url = ""
    return format_html(
        """
        <a href="{}"
            class="btn btn-sm btn-outline-success border me-2"
            data-bs-toggle="tooltip"
            data-bs-original-title="Edit"><i class="fe fe-edit-2"></i>
        </a>
        """,
        url,
    )


@register.simple_tag
def edit_link_for_form(inline_form):
    try:
        info = (inline_form.model_admin.opts.app_label, inline_form.model_admin.opts.model_name)
        url = reverse("admin:%s_%s_change" % info, args=(inline_form.original.pk,))
    except Exception:
        url = ""
    return format_html(
        """
        <a href="{}"
            class="btn btn-sm btn-outline-success border me-2"
            data-bs-toggle="tooltip"
            data-bs-original-title="Edit"><i class="fe fe-edit-2"></i>
        </a>
        """,
        url,
    )


@register.simple_tag
def dashboard_company_card():
    month_date = timezone.localtime().date().replace(day=1)
    count_company_all = Company.objects.count()
    count_company_until_last_month = Company.objects.filter(created_at__lt=month_date).count()
    current_month_grow = count_company_all - count_company_until_last_month
    span_arrow = format_html(
        """
        <span class="icn-box text-success fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-up'></i> {}</span>
        """,
        "{:,}".format(current_month_grow),
    )
    if current_month_grow < 0:
        span_arrow = format_html(
            """
            <span class="icn-box text-danger fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-down'></i> {}</span>
            """,
            "{:,}".format(current_month_grow),
        )
    return render_to_string(
        "admin/dashboard/company.html", {"title": "{:,}".format(count_company_all), "value": span_arrow}
    )


@register.simple_tag
def dashboard_greetings_card():
    count = Greetings.objects.count()
    return render_to_string(
        template_name="admin/dashboard/greetings.html",
        context={"title": "{:,}".format(count)},
    )


@register.simple_tag
def dashboard_waitlist_card():
    count = WaitList.objects.count()
    return render_to_string(
        template_name="admin/dashboard/waitlist.html",
        context={"title": "{:,}".format(count)},
    )


@register.simple_tag
def dashboard_user_card():
    month_date = timezone.localtime().date().replace(day=1)
    count_user_all = User.objects.count()
    count_user_until_last_month = User.objects.filter(date_joined__lt=month_date).count()
    current_month_grow = count_user_all - count_user_until_last_month
    span_arrow = format_html(
        """
        <span class="icn-box text-success fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-up'></i> {}</span>
        """,
        "{:,}".format(current_month_grow),
    )
    if current_month_grow < 0:
        span_arrow = format_html(
            """
            <span class="icn-box text-danger fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-down'></i> {}</span>
            """,
            "{:,}".format(current_month_grow),
        )

    return render_to_string("admin/dashboard/user.html", {"title": "{:,}".format(count_user_all), "value": span_arrow})


@register.simple_tag
def dashboard_ordo_order_card():
    order_objects = Order.objects.filter(order_type__in=[OrderType.ORDO_ORDER, OrderType.ORDER_PROCESSING])
    total_count, value = CustomTagHelper.calculate_growth_rate_and_get_payload(order_queryset=order_objects)
    return render_to_string("admin/dashboard/ordo_order.html", {"title": "{:,}".format(total_count), "value": value})


@register.simple_tag
def dashboard_order_count_card():
    vendor_order_objects = VendorOrder.objects.filter(status__in=[OrderStatus.OPEN, OrderStatus.CLOSED])
    total_count, value = CustomTagHelper.calculate_growth_rate_and_get_payload(order_queryset=vendor_order_objects)
    return render_to_string("admin/dashboard/vendor_order.html", {"title": "{:,}".format(total_count), "value": value})


@register.simple_tag
def dashboard_vendor_order_card():
    vendor_order_objects = VendorOrder.objects.filter(status__in=[OrderStatus.OPEN, OrderStatus.CLOSED])
    total_count, value = CustomTagHelper.calculate_growth_rate_and_get_payload(order_queryset=vendor_order_objects)
    return render_to_string("admin/dashboard/vendor_order.html", {"title": "{:,}".format(total_count), "value": value})


@register.simple_tag
def dashboard_order_price_card():
    month_date = timezone.localtime().date().replace(day=1)
    price_order_all = Order.objects.aggregate(Sum("total_amount"))["total_amount__sum"]
    price_order_until_last_month = Order.objects.filter(order_date__lt=month_date).aggregate(Sum("total_amount"))[
        "total_amount__sum"
    ]
    price_current_month_grow = price_order_all - price_order_until_last_month
    span_arrow = format_html(
        """
        <span class="icn-box text-success fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-up'></i> {}</span>
        """,
        "${:,}".format(price_current_month_grow),
    )
    if price_current_month_grow < 0:
        span_arrow = format_html(
            """
            <span class="icn-box text-danger fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-down'></i> {}</span>
            """,
            "${:,}".format(price_current_month_grow),
        )
    return render_to_string(
        "admin/dashboard/order_price.html", {"title": "{:,}".format(price_order_all), "value": span_arrow}
    )


@register.simple_tag
def dashboard_product_card():
    month_date = timezone.localtime().date().replace(day=1)
    count_product_all = Product.objects.count()
    count_product_until_last_month = Product.objects.filter(created_at__lt=month_date).count()
    current_month_grow = count_product_all - count_product_until_last_month
    span_arrow = format_html(
        """
        <span class="icn-box text-success fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-up'></i> {}</span>
        """,
        "{:,}".format(current_month_grow),
    )
    if current_month_grow < 0:
        span_arrow = format_html(
            """
            <span class="icn-box text-danger fw-semibold fs-13 me-1"><i class='fa fa-long-arrow-down'></i> {}</span>
            """,
            "{:,}".format(current_month_grow),
        )
    return render_to_string(
        "admin/dashboard/product.html", {"title": "{:,}".format(count_product_all), "value": span_arrow}
    )


@register.simple_tag
def dashboard_vendor_count_card():
    count_vendor_all = Vendor.objects.count()
    office_revenue = Office.objects.count() * 99
    return render_to_string(
        "admin/dashboard/vendor_count.html",
        {"title": "{:,}".format(count_vendor_all), "value": "${:,}".format(office_revenue)},
    )


@register.simple_tag
def dashboard_order_chart_data():
    price_values = (
        Order.objects.filter(order_date__gte="2021-01-01")
        .values("order_date")
        .annotate(total_price=Sum("total_amount"))
        .order_by("-order_date")
    )
    price_list = []
    for item in price_values:
        date_stamp = int(time.mktime(item["order_date"].timetuple())) * 1000
        total_price = float(item["total_price"])
        price_list.append([date_stamp, total_price])
    return price_list


@register.simple_tag
def dashboard_order_chart_card():
    date_first_this_year = timezone.localtime().date().replace(month=1, day=1)

    price_order_all = Order.objects.aggregate(Sum("total_amount"))["total_amount__sum"]
    price_order_until_last_year = Order.objects.filter(order_date__lt=date_first_this_year).aggregate(
        Sum("total_amount")
    )["total_amount__sum"]
    current_year_grow = price_order_all - price_order_until_last_year
    return render_to_string(
        "admin/dashboard/order_chart.html",
        {"title": "{:,}".format(price_order_all), "value": "${:,}".format(current_year_grow)},
    )


@register.simple_tag
def dashboard_available_opendental_key_count_card():
    total_count = OpenDentalKey.objects.count()
    used_count = Office.objects.get_all_queryset().filter(dental_api_id__isnull=False).count()
    available_count = total_count - used_count
    return render_to_string("admin/dashboard/opendental_key.html", {"remaining": "{:,}".format(available_count)})
