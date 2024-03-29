import csv
import json


def main():
    with open(
        "henryschein.json", "r", encoding="utf-8-sig"
    ) as f:
        data = json.load(f)

    with open("henry_schein.csv", "w") as f:
        csvwriter = csv.writer(f)
        csvwriter.writerow(["product_id", "promo"])
        for store_promotions in data:
            for product_id in store_promotions["ids"]:
                csvwriter.writerow([product_id, store_promotions["promocode"]])


if __name__ == "__main__":
    main()
