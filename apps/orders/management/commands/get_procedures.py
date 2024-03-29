import datetime

from django.core.management import BaseCommand

from apps.orders.helpers import ProcedureHelper, ProductHelper


class Command(BaseCommand):
    help = "Get procedures from Open Dental"

    def add_arguments(self, parser):
        """
        python manage.py get_procedures --from 2022-10-01T11:50:00 --type month --office 135
        """
        parser.add_argument(
            "--from",
            help="date",
        )

        parser.add_argument(
            "--to",
            help="date",
        )

        parser.add_argument(
            "--type",
            type=str,
            help="week or month",
        )

        parser.add_argument(
            "--office",
            type=str,
            help="office id",
        )
    def handle(self, *args, **options):
        day_from = datetime.datetime.fromisoformat(options["from"]) if options["from"] else None
        type = options["type"] if options["type"] else None
        office_id = int(options["office"]) if options["office"] else None
        ProcedureHelper.fetch_procedure_period(day_from, office_id, type)
