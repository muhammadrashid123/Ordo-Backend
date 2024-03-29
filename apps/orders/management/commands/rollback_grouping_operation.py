from django.core.management import BaseCommand
from django.db import connection

ROLLBACK_SQL = """
BEGIN;
UPDATE orders_product op
SET parent_id = ph.old_parent
FROM audit_productparenthistory ph
WHERE ph.operation_id = %(operation_id)s AND op.id = ph.product;

DELETE FROM audit_productparenthistory WHERE operation_id = %(operation_id)s;

DELETE FROM orders_product
WHERE parent_id IS NULL
      AND id > (
        SELECT max_parent_id_before
        FROM audit_rollbackinformation
        WHERE operation_id = %(operation_id)s
      )
      AND id <= (
        SELECT last_inserted_parent_id
        FROM audit_rollbackinformation
        WHERE operation_id = %(operation_id)s
      );
COMMIT;
"""


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("operation_id")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(ROLLBACK_SQL, {"operation_id": options["operation_id"]})
