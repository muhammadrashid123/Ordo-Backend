import asyncio
import datetime

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.db.models import CharField, F, Func, OuterRef, Subquery, Value
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django_admin_inline_paginator.admin import TabularInlinePaginated
from nested_admin.nested import NestedModelAdmin, NestedTabularInline

from apps.accounts.filters import CompanyDateFilter, VendorDateFilter
from apps.accounts.services.offices import OfficeService
from apps.accounts.tasks import bulk_send_company_members_invite, fetch_order_history
from apps.common.admins import AdminDynamicPaginationMixin, ReadOnlyAdminMixin
from apps.orders import models as om
from apps.orders.helpers import OrderHelper

from . import models as m
from .constants import INVITE_STATUS_LABELS
from .forms import OfficeVendorForm

admin.ModelAdmin.list_per_page = 50


@admin.register(m.User)
# class UserAdmin(admin.ModelAdmin):
class UserAdmin(AdminDynamicPaginationMixin, DefaultUserAdmin):
    list_display = (
        "username",
        "full_name",
        "companies",
        "date_joined",
        "role",
        "is_staff",
        "last_login",
    )
    readonly_fields = (
        "date_joined",
        "last_login",
    )
    list_filter = ()

    def get_queryset(self, request):
        company_names = (
            m.CompanyMember.objects.filter(user_id=OuterRef("pk"))
            .order_by()
            .annotate(companies=Func(F("company__name"), Value(", "), function="string_agg", output_field=CharField()))
            .values("companies")
        )
        return m.User.objects.annotate(companies=Subquery(company_names))

    @admin.display(description="Companies")
    def companies(self, obj):
        return obj.companies


INVITE_BUTTON_THRESHOLD = datetime.timedelta(days=3)


class CompanyMemberInline(ReadOnlyAdminMixin, NestedTabularInline):
    model = m.CompanyMember
    exclude = ("user", "token", "invited_by")
    fields = (
        "role",
        "user_full_name",
        "email",
        "office",
        "calculated_status",
        "date_joined",
        "date_invited",
        "is_active",
        "resend",
    )

    readonly_fields = (
        "user_full_name",
        "email",
        "office",
        "calculated_status",
        "date_joined",
        "date_invited",
        "is_active",
        "resend",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").with_can_reinvite()

    @admin.display(description="User")
    def user_full_name(self, obj):
        return obj.user.full_name

    @admin.display(description="Invite status")
    def calculated_status(self, obj):
        return INVITE_STATUS_LABELS[obj.calculated_status]

    @admin.display(description="Resend Invitation")
    def resend(self, obj: m.CompanyMember):
        if obj.invite_status == m.CompanyMember.InviteStatus.INVITE_SENT:
            return format_html(
                '<a class="btn btn-outline-primary" href="{}" class="link">Resend Invitation</a>',
                reverse_lazy("admin:admin_resend_invitation", args=[obj.pk]),
            )
        return ""


class OfficeVendorInline(ReadOnlyAdminMixin, NestedTabularInline, TabularInlinePaginated):
    model = m.OfficeVendor
    fields = ("vendor", "username", "password", "relink", "vendor_login")
    readonly_fields = ("vendor", "relink", "vendor_login")
    per_page = 10

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("vendor")

    @admin.display(description="Relink Vendor")
    def relink(self, obj):
        if obj.login_success:
            return ""
        else:
            return format_html(
                '<a class="btn btn-outline-primary btn-relink-vendor" href="{}" class="link">Relink Vendor</a>',
                reverse_lazy("admin:admin_relink_officevendor", args=[obj.pk]),
            )

    @admin.display(description="Vendor Login")
    def vendor_login(self, obj):
        url = obj.vendor.url
        return mark_safe("<a target='_blank' href='{}' class='btn btn-outline-primary'>Vendor Login</a>".format(url))


# Deliberately commenting out
# TODO: convert to BudgetInline
# class OfficeBudgetInline(NestedTabularInline):
#     model = m.OfficeBudget
#     fields = readonly_fields = (
#         "month",
#         "dental_budget_type",
#         "dental_budget",
#         "dental_spend",
#         "dental_percentage",
#         "office_budget_type",
#         "office_budget",
#         "office_spend",
#         "office_percentage",
#     )
#
#     def get_queryset(self, request):
#         current_date = timezone.localtime().date()
#         three_months_ago = current_date - relativedelta(months=3)
#         month = Month(year=current_date.year, month=three_months_ago.month)
#         return super().get_queryset(request).filter(month__gte=month).order_by("-month")


class OfficeOrdersInline(ReadOnlyAdminMixin, NestedTabularInline, TabularInlinePaginated):
    model = om.Order
    readonly_fields = (
        "id",
        "company",
        "office",
        "vendors",
        "total_price",
        "order_date",
        "order_type",
        "status",
        "total_items",
        "total_amount",
    )
    fields = ("vendors", "order_date", "total_items", "total_amount", "company", "order_type", "status")
    show_change_link = True
    per_page = 10

    @admin.display(description="Company")
    def company(self, obj):
        return obj.office.company

    @admin.display(description="Vendors")
    def vendors(self, objs):
        return ", ".join([vendor_order.vendor.name for vendor_order in objs.vendor_orders.all()])

    @admin.display(description="Order Total")
    def total_price(self, objs):
        return objs.total_amount

    def get_queryset(self, request):
        return super().get_queryset(request)


class SubscriptionInline(NestedTabularInline):
    model = m.Subscription
    fields = ("subscription_id", "start_on", "cancelled_on")
    readonly_fields = ("subscription_id",)


class OfficeInline(NestedTabularInline):
    model = m.Office
    inlines = [
        SubscriptionInline,
        OfficeVendorInline,
        # Deliberately commenting out
        # TODO: convert to BudgetInline
        # OfficeBudgetInline,
        OfficeOrdersInline,
    ]
    can_delete = False
    readonly_fields = ("logo_thumb", "name", "phone_number", "practice_software")
    exclude = ("dental_api", "website", "is_active")
    extra = 0

    @admin.display(description="Logo")
    def logo_thumb(self, obj):
        return mark_safe("<img src='{}'  width='30' height='30' />".format(obj.logo))


@admin.register(m.Company)
class CompanyAdmin(AdminDynamicPaginationMixin, NestedModelAdmin):
    list_display = (
        "name",
        "on_boarding_step",
        "order_count",
        "vendor_order_count",
        "ordo_order_volume",
        "date_joined",
        "is_active",
    )
    list_filter = (CompanyDateFilter,)
    search_fields = ("name",)
    inlines = (
        CompanyMemberInline,
        OfficeInline,
    )
    ordering = ("-on_boarding_step",)
    actions = ["delete_selected"]

    def get_queryset(self, request):
        first_joined = (
            m.CompanyMember.objects.filter(company=OuterRef("pk"), date_joined__isnull=False)
            .order_by("-date_joined")
            .values("date_joined")[:1]
        )
        return m.Company.objects.annotate(date_joined=Subquery(first_joined))

    def get_urls(self):
        urls = super().get_urls()
        return [
            path("relink-officevendor/<int:pk>/", self.relink_officevendor, name="admin_relink_officevendor"),
            path("resend-invitation/<int:pk>/", self.resend_invitation, name="admin_resend_invitation"),
            *urls,
        ]

    def relink_officevendor(self, request, pk):
        if request.method != "POST":
            return HttpResponse(status=405)
        form = OfficeVendorForm(request.POST)
        if not form.is_valid():
            return HttpResponse(status=400)

        officevendor = get_object_or_404(m.OfficeVendor, pk=pk)
        officevendor.username = form.cleaned_data["username"]
        officevendor.password = form.cleaned_data["password"]
        officevendor.save()

        res = asyncio.run(OrderHelper.login_vendor(officevendor, officevendor.vendor))
        if res:
            messages.add_message(request, messages.SUCCESS, "Relink success", extra_tags="success_relink")
            officevendor.login_success = True
            officevendor.save()
            fetch_order_history.delay(
                vendor_slug=officevendor.vendor.slug,
                office_id=officevendor.office_id,
            )
        else:
            messages.add_message(
                request, messages.WARNING, "Login failed with given credential", extra_tags="fail_relink"
            )

        return HttpResponse(status=200)

    def resend_invitation(self, request, pk):
        company_member = get_object_or_404(m.CompanyMember, pk=pk)
        company_member.invite_status = m.CompanyMember.InviteStatus.INVITE_SENT
        company_member.date_invited = timezone.localtime()
        company_member.save()
        bulk_send_company_members_invite.delay([company_member.pk])
        m.CompanyMemberInviteSchedule.cancel_for_member(company_member_id=company_member.pk)
        m.CompanyMemberInviteSchedule.create_for_member(company_member_id=company_member.pk)
        return redirect(request.META.get("HTTP_REFERER"))

    def delete_selected(self, request, queryset):
        for company in queryset:
            user_ids = company.members.filter(user__isnull=False).values_list("user_id", flat=True)
            m.User.objects.filter(pk__in=user_ids).update(is_active=False)
            for office in company.offices.all():
                OfficeService.cancel_subscription(office)
        queryset.update(ghosted=timezone.now(), is_active=False)

    @admin.display(description="Ordo Order Count")
    def order_count(self, obj):
        return obj.order_count

    @admin.display(description="Vendor Order Count")
    def vendor_order_count(self, obj):
        return obj.vendor_order_count

    @admin.display(description="Ordo Order Volume")
    def ordo_order_volume(self, obj):
        return f"${obj.ordo_order_volume}"

    @admin.display(description="Joined Date")
    def date_joined(self, obj):
        return obj.date_joined

    order_count.admin_order_field = "order_count"
    vendor_order_count.admin_order_field = "vendor_order_count"
    ordo_order_volume.admin_order_field = "ordo_order_volume"
    date_joined.admin_order_field = "date_joined"


@admin.register(m.UnlinkedOfficeVendor)
class UnlinkedVendorsAdmin(AdminDynamicPaginationMixin, NestedModelAdmin):
    model = m.UnlinkedOfficeVendor
    list_display = ("vendor", "company", "office", "edit_username", "edit_password", "relink", "vendor_login")
    list_filter = ["office"]
    ordering = ("office__company__name",)

    def get_queryset(self, request):
        unlinked_officevendors = m.UnlinkedOfficeVendor.objects.filter(
            login_success=False, office__company__is_active=True
        ).select_related("office", "vendor", "office__company")
        return unlinked_officevendors

    def get_urls(self):
        urls = super().get_urls()
        return [
            path("relink-officevendor/<int:pk>/", self.relink_officevendor, name="admin_relink_officevendor"),
            *urls,
        ]

    def relink_officevendor(self, request, pk):
        if request.method != "POST":
            return HttpResponse(status=405)
        form = OfficeVendorForm(request.POST)
        if not form.is_valid():
            return HttpResponse(status=400)

        officevendor = get_object_or_404(m.OfficeVendor, pk=pk)
        officevendor.username = form.cleaned_data["username"]
        officevendor.password = form.cleaned_data["password"]
        officevendor.save()

        res = asyncio.run(OrderHelper.login_vendor(officevendor, officevendor.vendor))
        if res:
            messages.add_message(request, messages.SUCCESS, "Relink success", extra_tags="success_relink")
            officevendor.login_success = True
            officevendor.save()
            fetch_order_history.delay(
                vendor_slug=officevendor.vendor.slug,
                office_id=officevendor.office_id,
            )
        else:
            messages.add_message(
                request, messages.WARNING, "Login failed with given credential", extra_tags="fail_relink"
            )

        return HttpResponse(status=200)

    @admin.display(description="Username", ordering="username")
    def edit_username(self, obj):
        return format_html('<input class="vTextField" value="{}">', obj.username)

    @admin.display(description="Password", ordering="password")
    def edit_password(self, obj):
        return format_html('<input class="vTextField" value="{}">', obj.password)

    @admin.display(description="Company", ordering="office__company__name")
    def company(self, obj):
        return obj.office.company.name

    @admin.display(description="Relink Vendor")
    def relink(self, obj):
        if obj.login_success:
            return ""
        else:
            return format_html(
                '<a class="btn btn-outline-primary btn-relink-vendor" href="{}" class="link">Relink Vendor</a>',
                reverse_lazy("admin:admin_relink_officevendor", args=[obj.pk]),
            )

    @admin.display(description="Vendor Login")
    def vendor_login(self, obj):
        url = obj.vendor.url
        return mark_safe("<a target='_blank' href='{}' class='btn btn-outline-primary'>Vendor Login</a>".format(url))


@admin.register(m.OfficeVendor)
class OfficeVendorAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    model = m.OfficeVendor
    list_display = ("vendor", "office", "login_success", "username", "password")
    list_filter = ["office", "login_success"]
    search_fields = ["username", "office__company__name", "office__name"]


@admin.register(m.Vendor)
class VendorAdmin(AdminDynamicPaginationMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "logo_thumb",
        "vendor_order_count",
        "url",
    )
    list_filter = (VendorDateFilter,)
    search_fields = ("name",)

    @admin.display(description="Logo")
    def logo_thumb(self, obj):
        return mark_safe("<img src='{}'  width='30' height='30' />".format(obj.logo))

    @admin.display(description="Vendor Order Count")
    def vendor_order_count(self, obj):
        return obj._vendor_order_count

    vendor_order_count.admin_order_field = "_vendor_order_count"

@admin.register(m.Region)
class RegionAdmin(admin.ModelAdmin):
    model = m.Region
    list_display = ("company", "region_name",)
    search_fields = ("company",)
