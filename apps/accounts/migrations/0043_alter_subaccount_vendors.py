# Generated by Django 4.2.1 on 2023-08-08 15:11

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0042_company_ghosted"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subaccount",
            name="vendors",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(
                    choices=[
                        ("henry_schein", "henry_schein"),
                        ("darby", "darby"),
                        ("patterson", "patterson"),
                        ("amazon", "amazon"),
                        ("benco", "benco"),
                        ("ultradent", "ultradent"),
                        ("implant_direct", "implant_direct"),
                        ("edge_endo", "edge_endo"),
                        ("dental_city", "dental_city"),
                        ("dcdental", "dcdental"),
                        ("crazy_dental", "crazy_dental"),
                        ("purelife", "purelife"),
                        ("skydental", "skydental"),
                        ("top_glove", "top_glove"),
                        ("bluesky_bio", "bluesky_bio"),
                        ("practicon", "practicon"),
                        ("midwest_dental", "midwest_dental"),
                        ("pearson", "pearson"),
                        ("salvin", "salvin"),
                        ("bergmand", "bergmand"),
                        ("biohorizons", "biohorizons"),
                        ("atomo", "atomo"),
                        ("orthoarch", "orthoarch"),
                        ("office_depot", "office_depot"),
                        ("safco", "safco"),
                        ("staples", "staples"),
                        ("net_32", "net_32"),
                    ]
                ),
                default=list,
                size=None,
            ),
        ),
    ]
