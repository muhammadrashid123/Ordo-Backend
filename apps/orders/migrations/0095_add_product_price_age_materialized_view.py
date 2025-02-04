# Generated by Django 4.2.1 on 2023-12-13 20:25

from django.db import migrations

SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS price_age
AS
WITH price_ages as (SELECT office_id,
                           vendor_id,
                           current_timestamp - last_price_updated as age
                    FROM orders_officeproduct op),
grouped_price_ages as (SELECT
    pa.office_id,
    pa.vendor_id,
    CASE
        WHEN age < '1 day'::interval THEN 1
        WHEN age < '3 days'::interval THEN 2
        WHEN age < '7 days'::interval THEN 3
        WHEN age < '15 days'::interval THEN 4
        WHEN age < '30 days'::interval THEN 5
        ELSE 6
    END as age_group
    FROM price_ages pa),
    group_names as (
        SELECT id, name
        FROM (
            VALUES
                (1, '<1d'),
                (2, '<3d'),
                (3, '<7d'),
                (4, '<15d'),
                (5, '<30d'),
                (6, '>30d')
        ) as t(id, name)
    ),
    group_stats as (SELECT gpa.office_id, gpa.vendor_id, gpa.age_group, count(*) as product_count
                    FROM grouped_price_ages gpa
                    GROUP BY gpa.office_id, gpa.vendor_id, gpa.age_group)
SELECT
    row_number() OVER (ORDER BY av.slug, ao.name) id,
    gs.office_id,
    ao.name as office_name,
    gs.vendor_id,
    av.slug as vendor_slug,
    gs.age_group,
    gn.name as category,
    COALESCE(gs.product_count, 0) as count
FROM group_names gn LEFT JOIN group_stats gs ON gn.id = gs.age_group
     JOIN accounts_office ao ON gs.office_id = ao.id
    JOIN accounts_vendor av ON gs.vendor_id = av.id
ORDER BY av.slug, ao.name
"""

REV_SQL = "DROP MATERIALIZED VIEW IF EXISTS price_age"

class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0094_update_materialized_view"),
    ]

    operations = [
        migrations.RunSQL(SQL, REV_SQL)
    ]
