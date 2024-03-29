from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.common.models import FlexibleForeignKey, TimeStampedModel


class Notification(TimeStampedModel):
    root_object_id = models.PositiveIntegerField()
    root_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    root_content_object = GenericForeignKey("root_content_type", "root_object_id")

    metadata = models.JSONField(null=True, blank=True)
    event = models.CharField(
        max_length=256,
        db_index=True,
        help_text="The class name of the notification class used to send.",
    )
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="NotificationRecipient", through_fields=("notification", "user")
    )


class NotificationRecipient(TimeStampedModel):
    notification = FlexibleForeignKey(Notification, related_name="notification_recipients")
    user = FlexibleForeignKey(settings.AUTH_USER_MODEL, related_name="notification_recipients")

    is_read = models.BooleanField(default=False, db_index=True)
    is_email_sent = models.BooleanField(db_index=True, default=False)
    is_sms_sent = models.BooleanField(db_index=True, default=False)
    is_push_sent = models.BooleanField(db_index=True, default=False)

    push_context = models.JSONField(null=True)
