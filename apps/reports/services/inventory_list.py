import datetime
import decimal
from typing import NamedTuple

from django.db import connection


class InventoryItem(NamedTuple):
    category: str
    item_description: str
    nickname: str
    last_ordered_from: str
    last_ordered_on: datetime.date
    last_quantity_ordered: int
    last_ordered_price: decimal.Decimal
    # quantity_on_hand: int
    # quantity_to_be_ordered: int


REPORT_SQL = """
WITH office_vops AS (
    SELECT DISTINCT ON (vop.product_id)
        vop.product_id, o.order_date, vop.quantity, vop.unit_price
    FROM orders_vendororderproduct vop
        JOIN orders_vendororder vo on vop.vendor_order_id = vo.id
        JOIN orders_order o ON vo.order_id = o.id
    WHERE o.office_id = %(office_id)s
    ORDER BY vop.product_id, o.order_date DESC
)
SELECT
    opc.name as category,
    op.description as item_description,
    oop.nickname as nickname,
    av.name,
    ovops.order_date as last_ordered_on,
    ovops.quantity as last_quantity_ordered,
    ovops.unit_price as  last_ordered_price
    FROM orders_officeproduct oop
        JOIN orders_product op ON oop.product_id = op.id
        JOIN orders_officeproductcategory opc on oop.office_product_category_id = opc.id
        JOIN accounts_vendor av ON op.vendor_id = av.id
        JOIN office_vops ovops ON ovops.product_id = oop.product_id
    WHERE
      oop.office_id = %(office_id)s
      AND oop.is_inventory
    ORDER BY ovops.order_date
"""


def inventory_list(office_id: int):
    with connection.cursor() as cur:
        cur.execute(REPORT_SQL, {"office_id": office_id})
        result = [InventoryItem(*row) for row in cur.fetchall()]
    return result
