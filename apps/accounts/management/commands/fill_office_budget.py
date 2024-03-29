from django.core.management import BaseCommand

from apps.accounts.tasks import update_office_budget


class Command(BaseCommand):
    def handle(self, *args, **options):
        update_office_budget()
