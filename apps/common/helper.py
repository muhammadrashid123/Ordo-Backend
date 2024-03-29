from typing import Union

import dateutil.relativedelta
from django.utils import timezone
from django.utils.html import format_html

from apps.orders.models import Order, VendorOrder


class CustomTagHelper:
    def __init__(self):
        pass

    @staticmethod
    def calculate_growth_rate_and_get_payload(order_queryset: Union[VendorOrder, Order]):
        this_month_first_date = timezone.localtime().date().replace(day=1)
        last_month_first_date = this_month_first_date + dateutil.relativedelta.relativedelta(months=-1)
        total_count = order_queryset.count()
        last_month_count = order_queryset.filter(
            order_date__gte=last_month_first_date, order_date__lt=this_month_first_date
        ).count()
        this_month_count = order_queryset.filter(order_date__gte=this_month_first_date).count()
        before_this_month_count = order_queryset.filter(order_date__lt=this_month_first_date).count()
        last_month_percentage = (
            round(last_month_count * 100 / before_this_month_count, 2) if before_this_month_count else 0
        )
        this_month_percentage = round(this_month_count * 100 / total_count, 2) if total_count else 0
        growth_rate = round(this_month_percentage - last_month_percentage, 2)
        arrow_status_class_name = "fa-long-arrow-up"
        color_status_class_name = "text-success"

        if growth_rate < 0:
            arrow_status_class_name = "fa-long-arrow-down"
            color_status_class_name = "text-danger"

        value = format_html(
            f"""
                <span class="icn-box {color_status_class_name} fw-semibold fs-13 me-1">
                    <i class='fa {arrow_status_class_name}'></i> {"{:,} %".format(growth_rate)}
                </span>
            """
        )

        return total_count, value
