# Generated by Django 4.2.1 on 2023-08-08 15:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0091_fill_budget_spend_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendororderproduct",
            name="budget_spend_type",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
    ]
