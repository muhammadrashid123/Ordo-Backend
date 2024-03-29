
from django.db import migrations

INSERT_SLUGS_SQL = """
DELETE FROM orders_procedurecategorylink;
INSERT INTO orders_procedurecategorylink (summary_category)
SELECT DISTINCT summary_category FROM orders_procedurecode WHERE summary_category IS NOT NULL;
"""

class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0050_auto_20230117_1454"),
    ]

    operations = [
        migrations.RunSQL(
            [INSERT_SLUGS_SQL],
        )
    ]
