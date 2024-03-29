from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django_rest_passwordreset.signals import reset_password_token_created

from apps.accounts.models import OfficeVendor as OfficeVendorModel
from apps.accounts.models import ShippingMethod as ShippingMethodModel

from .tasks import send_forgot_password_mail


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, *args, **kwargs):
    send_forgot_password_mail.delay(user_id=reset_password_token.user.id, token=reset_password_token.key)


@receiver(m2m_changed, sender=OfficeVendorModel.shipping_options.through)
def remove_shipping_method_through_office_vendor(sender, **kwargs):
    action = kwargs["action"]
    if action == "pre_clear":
        shipping_methods_pks = kwargs["instance"].shipping_options.values_list("pk")
        shipping_methods = ShippingMethodModel.objects.filter(pk__in=shipping_methods_pks)
        shipping_methods.delete()
