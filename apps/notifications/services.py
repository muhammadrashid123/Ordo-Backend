from django.db.models.query import QuerySet

from apps.notifications.models import NotificationRecipient


class NotificationService:
    @staticmethod
    def mark_all_as_read(user, queryset=None):
        if queryset is not None:
            if isinstance(queryset, QuerySet):
                queryset = queryset.filter(user=user)
            else:
                queryset = [notification for notification in queryset if notification.user == user]
        else:
            queryset = NotificationRecipient.objects.filter(user=user, is_read=False)

        for notification in queryset:
            notification.is_read = True

        NotificationRecipient.objects.bulk_update(queryset, fields=["is_read"])

    @staticmethod
    def mark_as_read(notification: NotificationRecipient):
        notification.is_read = True
        notification.save()
