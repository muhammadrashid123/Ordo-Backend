import logging

from django.core.management import BaseCommand

from apps.accounts.constants import MONTHS_BACKWARDS
from apps.accounts.tasks import fill_office_budget_full

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--office", type=int)
        parser.add_argument("--months", type=int, default=MONTHS_BACKWARDS)

    def handle(self, *args, **options):
        logging.basicConfig(level="INFO")
        office_id = options.get("office")
        fill_office_budget_full(office_id, options["months"])
