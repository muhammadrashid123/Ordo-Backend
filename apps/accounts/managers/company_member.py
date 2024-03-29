from datetime import timedelta

from django.db import models
from django.db.models import Case, Value, When
from django.utils import timezone

from apps.accounts.constants import (
    CALCULATED_STATUS_ACCEPTED,
    CALCULATED_STATUS_EXPIRED,
    CALCULATED_STATUS_SENT,
    INVITE_EXPIRES_DAYS,
)
from apps.accounts.managers.base_active import BaseActiveManager


class CompanyMemberQuerySet(models.QuerySet):
    def with_can_reinvite(self):
        from apps.accounts.models import CompanyMember

        return self.annotate(
            calculated_status=Case(
                When(invite_status=CompanyMember.InviteStatus.INVITE_APPROVED, then=Value(CALCULATED_STATUS_ACCEPTED)),
                When(
                    invite_status=CompanyMember.InviteStatus.INVITE_SENT,
                    date_invited__lt=timezone.now() - timedelta(days=INVITE_EXPIRES_DAYS),
                    then=Value(CALCULATED_STATUS_EXPIRED),
                ),
                default=CALCULATED_STATUS_SENT,
                output_field=models.IntegerField(),
            ),
        )


class CompanyMemberActiveManager(BaseActiveManager):
    _queryset_class = CompanyMemberQuerySet
