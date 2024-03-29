from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.accounts.models import CompanyMember, Office, User
from apps.reports.formatters.csv import export_to_csv
from apps.reports.services.inventory_list import inventory_list
from apps.reports.utils import get_content_disposition_header


class InventoryListAPIView(APIView):
    def get(self, request, **kwargs):
        office_id = request.query_params.get("office_id")
        user: User = request.user
        office = Office.objects.filter(pk=office_id).first()
        if not office:
            raise ValidationError("Office does not exist")
        if not CompanyMember.objects.filter(office_id=office.id, user=user).exists():
            raise PermissionDenied("User does not have permissions to access this endpoint")
        rows = inventory_list(office_id)
        date_str = timezone.localtime().strftime("%Y%m%d%H%M")
        response = HttpResponse(export_to_csv(rows), content_type="text/csv")
        filename = f"{office.name}-{date_str}.csv"
        response.headers["Content-Disposition"] = get_content_disposition_header(filename)
        return response
