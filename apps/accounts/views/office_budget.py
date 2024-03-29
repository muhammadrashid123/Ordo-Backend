import json
import logging
from datetime import datetime, timedelta

from django import db
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts import filters as f
from apps.accounts import models as m
from apps.accounts import serializers as s
from apps.accounts.helper import OfficeBudgetHelper
from apps.common.month import Month
from apps.orders.serializers import DateRangeQuerySerializer

logger = logging.getLogger(__name__)


class BudgetViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = m.Budget.objects.all()
    filterset_class = f.BudgetFilter

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return s.BudgetUpdateSerializer
        if self.action == "create":
            return s.BudgetCreateSerializer
        return self.get_response_serializer_class()

    def get_response_serializer_class(self):
        if self.action == "stats":
            return s.BudgetStatsSerializer
        return s.BudgetSerializer

    def get_queryset(self):
        qs = super().get_queryset().filter(office_id=self.kwargs["office_pk"])
        if self.action in ("list", "retrieve", "get_chart_data"):
            qs = qs.prefetch_related("subaccounts")
        return qs

    def create(self, request, *args, **kwargs):
        on_boarding_step = request.data.pop("on_boarding_step", None)
        company = get_object_or_404(m.Company, pk=self.kwargs["company_pk"])
        if on_boarding_step and company.on_boarding_step < on_boarding_step:
            company.on_boarding_step = on_boarding_step
            company.save()

        this_month = Month.from_date(timezone.localdate())
        # request.data.setdefault("office", self.kwargs["office_pk"])
        # request.data.setdefault("month", now_date)

        serializer_class = self.get_serializer_class()
        serializer = serializer_class(
            data=request.data,
            context={**self.get_serializer_context(), "office_pk": self.kwargs["office_pk"], "month": this_month},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance = serializer.instance
        serializer_class = self.get_response_serializer_class()
        serializer = serializer_class(instance=instance)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=["get"], url_path="charts")
    def get_chart_data(self, request, *args, **kwargs):
        this_month = Month.from_date(timezone.localdate().replace(day=1))
        end_month = this_month.next_month()
        start_month = end_month - 12
        office_id = kwargs["office_pk"]
        with db.connection.cursor() as cur:
            cur.execute(
                "SELECT * FROM budget_chart_data(%s, %s, %s)",
                [office_id, start_month._date, end_month._date],
            )
            ret = json.loads(cur.fetchone()[0])
        return Response(ret)

    def update(self, request, *args, **kwargs):
        kwargs.setdefault("partial", True)
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        serializer_class = self.get_response_serializer_class()
        serializer = serializer_class(instance=instance)
        return Response(serializer.data)

    @action(detail=False, url_path="stats", methods=["get"])
    def stats(self, request, *args, **kwargs):
        month = self.request.query_params.get("month", "")
        office_id = self.kwargs["office_pk"]
        try:
            requested_date = datetime.strptime(month, "%Y-%m")
        except ValueError:
            requested_date = timezone.localdate()
        month = Month.from_date(requested_date)
        current_month_budget = OfficeBudgetHelper.get_or_create_budget(office_id=office_id, month=month)
        with db.connection.cursor() as cur:
            cur.execute(
                "SELECT * FROM budget_full_stats(%s, %s, %s)",
                [office_id, month.first_day(), month.next_month().first_day() - timedelta(days=1)],
            )
            full_stats = json.loads(cur.fetchone()[0])
        slug_id_mapping = {
            slug: subid
            for subid, slug in m.Subaccount.objects.filter(budget=current_month_budget).values_list("id", "slug")
        }
        full_stats = [{**full_stat, "id": slug_id_mapping[full_stat["slug"]]} for full_stat in full_stats]
        sorted_full_stats = sorted(full_stats, key=lambda x: x["name"] == "Miscellaneous")
        serializer = self.get_serializer(current_month_budget)
        return Response({**serializer.data, "subaccounts": sorted_full_stats})

    @action(detail=False, methods=["get"])
    def full_stats(self, request, *args, **kwargs):
        office_id = self.kwargs["office_pk"]
        query_serializer = DateRangeQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        attrs = query_serializer.validated_data
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        start_month = Month.from_date(start_date)
        end_month = Month.from_date(end_date)
        cur_month = start_month
        while cur_month <= end_month:
            OfficeBudgetHelper.get_or_create_budget(office_id=office_id, month=cur_month)
            cur_month += 1
        with db.connection.cursor() as cur:
            cur.execute("SELECT * FROM budget_full_stats(%s, %s, %s)", [office_id, start_date, end_date])
            result = json.loads(cur.fetchone()[0])
        sorted_full_stats = sorted(result, key=lambda x: x["name"] == "Miscellaneous")
        return Response(sorted_full_stats)
