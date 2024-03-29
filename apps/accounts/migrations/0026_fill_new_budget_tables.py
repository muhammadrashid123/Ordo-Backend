# Generated by Django 4.2.1 on 2023-06-05 18:57
from collections import defaultdict

from django.db import migrations

NONE = 0
PRODUCTION = 1
COLLECTION = 2

BT2BASIS = {
    "production": PRODUCTION,
    "collection": COLLECTION
}


def fill_budget(apps, schema_editor):
    OfficeBudget = apps.get_model("accounts", "OfficeBudget")
    Budget = apps.get_model("accounts", "Budget")
    Subaccount = apps.get_model("accounts", "Subaccount")
    office_budgets = defaultdict(defaultdict)
    for ob in OfficeBudget.objects.all():
        office_budgets[ob.office_id][ob.month] = ob
    for office_id, budgets in office_budgets.items():
        for month, ob in budgets.items():
            budget_type = ob.dental_budget_type

            if ob.adjusted_production:
                adjusted_production = ob.adjusted_production
            elif budget_type == 'production':
                adjusted_production = ob.dental_total_budget
            else:
                adjusted_production = 0

            if ob.collection:
                collection = ob.collection
            elif budget_type == "collection":
                collection = ob.dental_total_budget
            else:
                collection = 0

            budget = Budget.objects.create(
                office_id=ob.office_id,
                month=month,
                adjusted_production=adjusted_production,
                collection=collection,
                basis=BT2BASIS[ob.dental_budget_type]
            )
            Subaccount.objects.create(
                budget=budget,
                slug="dental",
                name="Dental",
                percentage=ob.dental_percentage,
                spend=ob.dental_spend
            )
            Subaccount.objects.create(
                budget=budget,
                slug="office",
                name="Office",
                percentage=ob.office_percentage,
                spend=ob.office_spend
            )
            Subaccount.objects.create(
                budget=budget,
                slug="miscellaneous",
                name="Miscellaneous",
                percentage=0,
                spend=ob.miscellaneous_spend
            )



class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0025_budget_subaccount"),
    ]

    operations = [
        migrations.RunPython(fill_budget, migrations.RunPython.noop)
    ]
