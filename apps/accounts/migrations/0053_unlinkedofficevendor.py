# Generated by Django 4.2.1 on 2023-11-14 23:04

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0052_merge_20231114_0734"),
    ]

    operations = [
        migrations.CreateModel(
            name="UnlinkedOfficeVendor",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("accounts.officevendor",),
        ),
    ]
