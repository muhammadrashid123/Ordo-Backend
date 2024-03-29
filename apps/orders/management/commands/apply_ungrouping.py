import csv
import dataclasses
import uuid
from collections import defaultdict
from itertools import groupby
from typing import DefaultDict, Dict, List, NamedTuple, Optional, Set, Tuple

from django.core.management import BaseCommand
from django.db.models import Max
from django.db.transaction import atomic

from apps.audit.models import ProductParentHistory, RollbackInformation
from apps.orders.models import Product


@dataclasses.dataclass
class ProductMovement:
    source: Optional[int] = None
    destination: Optional[int] = None


class MappingResults(NamedTuple):
    db_products: Dict[int, Product]
    parent_to_children: DefaultDict[int, list[Product]]
    subgroup_to_product_ids: DefaultDict[int, set[int]]

    @property
    def all_products(self):
        return {p.id: p for product_list in self.parent_to_children.values() for p in product_list}

    def find_subgroup_by_name(self, name: str):
        """
        Given parent_name find subgroup containing product with matching name
        """
        for subgroup_id, subgroup_product_ids in self.subgroup_to_product_ids.items():
            subgroup_product_names = {self.db_products[product_id].name for product_id in subgroup_product_ids}
            if name in subgroup_product_names:
                return subgroup_id

    def find_parent_to_subgroup_mapping(self) -> Tuple[Dict[int, int], bool]:
        parent2subgroup: dict[int, int] = {}
        all_found = True
        # Find matching parents in existing subgroups
        for parent_id, product_ids in self.parent_to_children.items():
            parent_name = self.db_products[parent_id].name

            # See which subgroup contains name which is equal to parent.name
            subgroup_id = self.find_subgroup_by_name(parent_name)
            if subgroup_id is None:
                all_found = False
            else:
                parent2subgroup[parent_id] = subgroup_id
        return parent2subgroup, all_found


class Command(BaseCommand):
    """
    Given analysis script split existing product groups into
    multiple groups and record activity to make rollback
    possible
    """

    def add_arguments(self, parser):
        parser.add_argument("csvfile")

    def read_items(self, csvfile):
        """
        Go through analysis csv file and skip rows having keep equal to 1
        """
        with open(csvfile) as f:
            reader = csv.DictReader(f, dialect="excel-tab")
            for row in reader:
                yield row

    def calculate_parent_mappings(self, manufacturer_number, csv_items) -> MappingResults:
        parent_to_children: DefaultDict[int, List[Product]] = defaultdict(set)
        subgroup_to_product_ids: DefaultDict[int, Set[int]] = defaultdict(set)

        db_products: dict[int, Product] = {
            p.id: p for p in Product.objects.filter(manufacturer_number=manufacturer_number).exclude(parent_id=None)
        }

        csv_product_ids = {int(e["id"]) for e in csv_items}

        # Making sure that ids of child products in CSV matches what we have in database
        assert csv_product_ids == {k for k, v in db_products.items() if v.parent_id}

        # Creating dict parent_id -> list[Product]
        for product in db_products.values():
            if product.parent_id:
                parent_to_children[product.parent_id].add(product)

        # Parent products
        for parent_product in Product.objects.filter(id__in={p.parent_id for p in db_products.values()}):
            db_products[parent_product.id] = parent_product

        # Creating dict subgroup_id -> list[product_id]
        for e in csv_items:
            subgroup_to_product_ids[int(e["subgroup_id"])].add(int(e["id"]))
        return MappingResults(db_products, parent_to_children, subgroup_to_product_ids)

    def create_missing_parents(self, mapping_result: MappingResults, existing_subgroups) -> Dict[int, int]:
        parent2subgroup = {}
        subgroups_missing_matching_parents = set(mapping_result.subgroup_to_product_ids.keys()) - existing_subgroups
        for subgroup_id in subgroups_missing_matching_parents:
            # Get first item from set and use it as parent item name
            subgroup_items = iter(mapping_result.subgroup_to_product_ids[subgroup_id])
            subgroup_item = next(subgroup_items)
            child_product = mapping_result.db_products[subgroup_item]

            # Create parent product
            parent_product = Product.objects.create(
                name=child_product.name, manufacturer_number=child_product.manufacturer_number, is_special_offer=False
            )

            # Register parent to subgroup
            parent2subgroup[parent_product.id] = subgroup_id
            mapping_result.parent_to_children[parent_product.id] = set()
        return parent2subgroup

    @atomic
    def handle(self, *args, **options):
        # ID of this execution id, used for rollback
        operation_id = uuid.uuid4()
        max_parent_id_before = Product.objects.filter(parent_id__isnull=True).aggregate(Max("id"))["id__max"]
        last_inserted_parent_id = 0
        history = []

        csv_items = list(self.read_items(options["csvfile"]))
        csv_items.sort(key=lambda x: (x["manufacturer_number"], x["subgroup_id"]))

        counter = 0
        for manufacturer_number, items in groupby(csv_items, key=lambda x: x["manufacturer_number"]):
            counter += 1
            if counter % 100 == 0:
                print(counter)
            items = list(items)
            mapping_result = self.calculate_parent_mappings(manufacturer_number, items)
            parent2subgroup, all_found = mapping_result.find_parent_to_subgroup_mapping()
            if not all_found:
                continue

            # Creating new parent products
            existing_subgroups = set(parent2subgroup.values())
            created_parent2subgroup = self.create_missing_parents(mapping_result, existing_subgroups)
            if created_parent2subgroup:
                last_inserted_parent_id = max(created_parent2subgroup.keys())
                parent2subgroup.update(created_parent2subgroup)
            subgroup2parent = {v: k for k, v in parent2subgroup.items()}
            product_to_subgroup_id = {item: k for k, v in mapping_result.subgroup_to_product_ids.items() for item in v}

            # Once we have complete parent 2 subgroup mapping we can proceed
            movement = defaultdict(ProductMovement)
            for child_product in mapping_result.all_products.values():
                movement[child_product.id] = ProductMovement(
                    source=child_product.parent_id,
                    destination=subgroup2parent[product_to_subgroup_id[child_product.id]],
                )
            products_to_update = []
            for product_id, product_movement in movement.items():
                if product_movement.source == product_movement.destination:
                    continue
                product = mapping_result.db_products[product_id]
                product.parent_id = product_movement.destination
                products_to_update.append(product)
                history.append(
                    ProductParentHistory(
                        operation_id=operation_id,
                        product=product_id,
                        old_parent=product_movement.source,
                        new_parent=product_movement.destination,
                    )
                )
            Product.objects.bulk_update(products_to_update, ["parent_id"])

        ProductParentHistory.objects.bulk_create(history)
        RollbackInformation.objects.create(
            operation_id=operation_id,
            last_inserted_parent_id=last_inserted_parent_id,
            max_parent_id_before=max_parent_id_before,
        )
        print(operation_id)
