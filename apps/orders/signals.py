from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import OfficeVendor
from apps.orders.models import VendorOrder


@receiver(post_save, sender=VendorOrder)
def create_vendor_order(sender, instance, created, **kwargs):
    if created and not instance.shipping_option:
        office_vendor = OfficeVendor.objects.filter(office=instance.order.office, vendor=instance.vendor).first()
        if not office_vendor:
            return
        instance.shipping_option = office_vendor.default_shipping_option
        instance.save()
