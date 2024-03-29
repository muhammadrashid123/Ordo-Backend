import decimal
from typing import Dict, Optional, Tuple

from django.utils import timezone

from apps.accounts.models import Budget, Office, OfficeSetting, Subscription
from apps.accounts.services.stripe import (
    cancel_subscription as stripe_cancel_subscription,
)
from apps.accounts.services.stripe import (
    create_subscription as stripe_create_subscription,
)
from apps.common import messages as msgs
from apps.common.month import Month


class OfficeService:
    @staticmethod
    def get_office(office_pk: int):
        return Office.objects.get(id=office_pk)

    @staticmethod
    def get_office_budget(office_pk: int, month: Optional[Month] = None) -> Optional[Budget]:
        if month is None:
            current_date = timezone.localtime().date()
            month = Month(year=current_date.year, month=current_date.month)

        return Budget.objects.filter(office_id=office_pk, month=month).prefetch_related("subaccounts").first()

    @staticmethod
    def get_office_remaining_budget(office_pk: int) -> Dict[str, decimal.Decimal]:
        office_budget = OfficeService.get_office_budget(office_pk)
        if not office_budget:
            return {}
        return {
            subaccount.slug: office_budget.total_budget * subaccount.percentage - subaccount.spend
            for subaccount in office_budget.subaccounts.all()
        }

    @staticmethod
    def get_office_setting(office_pk: int):
        return OfficeSetting.objects.get(office_id=office_pk)

    @staticmethod
    def cancel_subscription(office: Office) -> Tuple[bool, str]:
        active_subscription = office.subscriptions.filter(cancelled_on__isnull=True).order_by("-updated_at").first()
        if active_subscription is None:
            return False, msgs.OFFICE_HAS_NO_SUBSCRIPTION
        try:
            stripe_cancel_subscription(active_subscription.subscription_id)
        except Exception as e:
            return False, f"{e}"
        else:
            active_subscription.cancelled_on = timezone.localtime()
            active_subscription.save()
            return True, "Subscription cancelled successfully"

    @staticmethod
    def create_subscription(office: Office) -> Tuple[bool, str]:
        active_subscription = office.subscriptions.filter(cancelled_on__isnull=True).order_by("-updated_at").first()
        if active_subscription:
            return False, msgs.OFFICE_HAS_ACTIVE_SUBSCRIPTION
        try:
            subscription = stripe_create_subscription(office.card.customer_id)
        except Exception as e:
            return False, f"{e}"
        else:
            Subscription.objects.create(subscription_id=subscription.id, start_on=timezone.localtime(), office=office)
            return True, "Subscription renewed successfully"
