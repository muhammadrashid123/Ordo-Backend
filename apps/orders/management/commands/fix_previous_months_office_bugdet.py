from django.core.management import BaseCommand
from django.db.models import Sum

from apps.accounts.helper import OfficeBudgetHelper
from apps.accounts.models import Budget
from apps.orders.models import VendorOrder, YearMonth


class Command(BaseCommand):
    help = "Fix inventory missing product"

    def handle(self, *args, **options):
        monthly_budget_by_offices = (
            VendorOrder.objects.annotate(month=YearMonth("order_date"))
            .order_by("order__office", "-month")
            .values("order__office", "month")
            .annotate(total_amount=Sum("total_amount"))
        )
        offices_first_budgets = {}
        for monthly_budget_by_office in monthly_budget_by_offices:
            office_id = monthly_budget_by_office["order__office"]

            try:
                offices_first_budgets[office_id] = Budget.objects.get(
                    office_id=office_id, month=monthly_budget_by_office["month"]
                )
            except Budget.DoesNotExist:
                if office_id in offices_first_budgets:
                    latest_office_budget = offices_first_budgets[office_id]
                else:
                    latest_office_budget = Budget.objects.filter(office_id=office_id).order_by("-month").first()
                    offices_first_budgets[office_id] = latest_office_budget
                OfficeBudgetHelper.clone_budget(
                    budget=latest_office_budget,
                    overrides=dict(
                        month=monthly_budget_by_office["month"],
                        dental_spend=monthly_budget_by_office["total_amount"],
                        office_spend=0,
                        miscellaneous_spend=0,
                    ),
                )
