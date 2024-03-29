from django.db import models

PRODUCT_CATEGORY_STATS_BY_VENDOR = """
WITH collapsed AS (
        SELECT DISTINCT ON (ofp.vendor_id, op.parent_id)
        ofp.id, ofp.vendor_id, ofp.office_product_category_id
        FROM "orders_officeproduct" ofp
               LEFT OUTER JOIN "orders_product" op ON (ofp.product_id = op.id)
        WHERE ofp.is_inventory AND ofp.office_id = %(office_id)s AND ofp.vendor_id in %(vendor_ids)s
        ORDER BY ofp.vendor_id, op.parent_id ASC, ofp."last_order_date" DESC
    ),
    stats AS (
        SELECT
            COUNT(*) as count,
            array_agg(DISTINCT c.office_product_category_id) as categories,
            c.vendor_id
        FROM collapsed c
        GROUP BY c.vendor_id
    )
SELECT av.*,
    COALESCE(stats.count, 0) as count,
    COALESCE(stats.categories, '{}'::int[]) as categories
    FROM stats
        LEFT JOIN accounts_vendor av ON stats.vendor_id = av.id
    ORDER BY av.name;
"""


class VendorQuerySet(models.QuerySet):
    def with_stats(self, office_id, vendor_ids):
        return self.raw(
            PRODUCT_CATEGORY_STATS_BY_VENDOR, params={"office_id": office_id, "vendor_ids": tuple(vendor_ids)}
        )


class VendorManager(models.Manager):
    _queryset_class = VendorQuerySet

    def get_queryset(self):
        return super().get_queryset().exclude(is_manual=True)
