import csv
import io
import re
from typing import List, NamedTuple


def export_to_csv(rows: List) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    nt_class: NamedTuple = rows[0].__class__
    fieldnames = nt_class._fields
    writer.writerow(fieldnames)

    for row in rows:
        # Check if each attribute is not None before replacing '\n' with ''
        if row.item_description is not None:
            item_description = re.sub(r"\n+", " ", row.item_description)
        else:
            item_description = ""

        #
        item_description = item_description.split("  ")[0]
        item_description = item_description.split(" 	")[0]
        item_description = item_description.replace("\n", "") if item_description is not None else ""

        category = row.category.replace("\n", "") if row.category is not None else ""
        nickname = row.nickname.replace("\n", "") if row.nickname is not None else ""
        last_ordered_from = row.last_ordered_from.replace("\n", "") if row.last_ordered_from is not None else ""
        last_ordered_price = row.last_ordered_price

        writer.writerow(
            [
                category,
                item_description,
                nickname,
                last_ordered_from,
                row.last_ordered_on,
                last_ordered_price,
                row.last_quantity_ordered,
            ]
        )

    return buffer.getvalue()
