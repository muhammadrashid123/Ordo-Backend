from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0030_officeproduct_last_order_price'),
    ]

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql="""
              ALTER TABLE orders_product ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(product_id, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(name,'')), 'B')
              ) STORED;
            """,
            reverse_sql="""
              ALTER TABLE orders_product DROP COLUMN search_vector;
            """
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX orders_product_search_idx ON orders_product USING GIN (search_vector);
            """,

            reverse_sql="""
            DROP INDEX IF EXISTS orders_product_search_idx;
            """
        ),
    ]
