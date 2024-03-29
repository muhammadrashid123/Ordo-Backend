# Generated by Django 4.2.1 on 2023-07-28 19:41

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0040_fill_creators"),
    ]

    operations = [
        migrations.AlterField(
            model_name="companymember",
            name="office",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="accounts.office"),
        ),
    ]
