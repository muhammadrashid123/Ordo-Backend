from django.db import models

from apps.accounts.models import Office


class IntegrationClientDetails(models.Model):
    office = models.ForeignKey(
        Office, null=True, blank=True, on_delete=models.CASCADE, related_name="integration_client_details"
    )
    vendor_customer_number = models.CharField(max_length=70, blank=True, null=True)

    def __str__(self):
        if self.vendor_customer_number is not None:
            return str(self.vendor_customer_number)
        else:
            return "No vendor_customer_number"
