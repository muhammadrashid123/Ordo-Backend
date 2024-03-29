from django.db.models import Manager


class ActiveSubscriptionManager(Manager):
    def get_queryset(self):
        return super().get_queryset().filter(cancelled_on__isnull=True)
