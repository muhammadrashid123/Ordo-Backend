import logging

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_204_NO_CONTENT
from rest_framework.viewsets import ModelViewSet

from apps.accounts import filters as f
from apps.accounts import models as m
from apps.accounts import serializers as s
from apps.accounts import tasks as accounts_tasks
from apps.common import messages
from apps.common.month import Month

logger = logging.getLogger(__name__)


class CompanyMemberViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_class = f.CompanyMemberFilter

    def get_queryset(self):
        queryset = m.CompanyMember.objects.filter(company_id=self.kwargs["company_pk"])
        current_time = timezone.localtime()
        if self.action == "list":
            queryset = queryset.select_related(
                "office",
                "office__dental_api",
            ).prefetch_related(
                "office__addresses",
                "office__vendors",
                Prefetch(
                    "office__budget_set",
                    m.Budget.objects.filter(month=Month(year=current_time.year, month=current_time.month)),
                    to_attr="prefetched_current_budget",
                ),
                "office__settings",
            )
        return queryset

    def get_serializer_class(self):
        if self.action in ("update", "create"):
            return s.CompanyMemberUpdateSerializer
        else:
            return s.CompanyMemberSerializer

    def create(self, request, *args, **kwargs):
        request.data.setdefault("company", self.kwargs["company_pk"])
        data = request.data
        data["invited_by"] = request.user.id
        serializer = self.get_serializer(data=request.data)
        serializer.initial_data["date_invited"] = timezone.localtime()
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        company_member = serializer.instance
        accounts_tasks.bulk_send_company_members_invite.delay([company_member.pk])
        m.CompanyMemberInviteSchedule.create_for_member(company_member.pk)
        return Response(serializer.data, status=HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer_class = self.get_serializer_class()
        data = request.data
        data["invited_by"] = request.user.id
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        if instance.role != m.User.Role.ADMIN:
            return Response({"message": messages.NOT_ALLOWED_FOR_USER}, status=status.HTTP_400_BAD_REQUEST)

        is_only_one_admin = (
            m.CompanyMember.objects.filter(company_id=instance.company_id, role=m.User.Role.ADMIN).count() == 1
        )

        if is_only_one_admin and serializer.validated_data["role"] != m.User.Role.ADMIN:
            return Response({"message": messages.NO_ADMIN_MEMBER}, status=status.HTTP_400_BAD_REQUEST)

        instance.role = serializer.validated_data["role"]
        instance.save()
        return Response({"message": ""})

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_invite(self, request, *args, **kwargs):
        serializer = s.CompanyMemberBulkInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        emails = [member["email"] for member in serializer.validated_data["members"]]
        with transaction.atomic():
            company = m.Company.objects.get(id=self.kwargs["company_pk"])
            on_boarding_step = serializer.validated_data.get("on_boarding_step")
            if on_boarding_step:
                company.on_boarding_step = serializer.validated_data.get("on_boarding_step")
                company.save()

            users = m.User.objects.in_bulk(emails, field_name="username")
            recipients = []
            for member in serializer.validated_data["members"]:
                pre_associated_offices = set(
                    m.CompanyMember.objects.filter(company_id=kwargs["company_pk"], email=member["email"]).values_list(
                        "office", flat=True
                    )
                )

                offices = member.get("offices")
                if offices:
                    offices = set(offices)
                    to_be_removed_offices = pre_associated_offices

                    if to_be_removed_offices:
                        m.CompanyMember.objects.filter(
                            email=member["email"], office_id__in=to_be_removed_offices
                        ).delete()

                    company_members = [
                        m.CompanyMember.objects.create(
                            company_id=kwargs["company_pk"],
                            office=office,
                            email=member["email"],
                            role=member["role"],
                            user=users.get(member["email"], None),
                            date_invited=timezone.localtime(),
                            invited_by=request.user,
                        )
                        for i, office in enumerate(offices)
                    ]
                    # We send only one email even if there are more offices
                    # TODO: feels like office binding should be in some other table
                    recipients.append(company_members[0])
                else:
                    company_member = m.CompanyMember.objects.create(
                        company_id=kwargs["company_pk"],
                        office=None,
                        email=member["email"],
                        role=member["role"],
                        user=users.get(member["email"], None),
                        date_invited=timezone.localtime(),
                        invited_by=request.user,
                    )
                    recipients.append(company_member)

        accounts_tasks.bulk_send_company_members_invite.delay([o.pk for o in recipients])

        for recipient in recipients:
            m.CompanyMemberInviteSchedule.create_for_member(recipient.pk)
        # TODO: return 204 no content, check with FE
        return Response({})

    @action(detail=True, methods=["post"])
    def reinvite_member(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.invite_status = m.CompanyMember.InviteStatus.INVITE_SENT
        instance.date_invited = timezone.localtime()
        instance.regenerate_token()
        instance.save()
        accounts_tasks.bulk_send_company_members_invite([instance.pk])
        m.CompanyMemberInviteSchedule.create_for_member(instance.pk)
        return Response(status=HTTP_204_NO_CONTENT)
