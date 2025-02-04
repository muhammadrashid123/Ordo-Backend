# Generated by Django 4.2.1 on 2023-07-23 00:00

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0034_remove_companymember_token_expires_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyMemberInviteSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scheduled", models.DateTimeField()),
                ("actual", models.DateTimeField(null=True)),
                (
                    "company_member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invite_schedules",
                        to="accounts.companymember",
                    ),
                ),
            ],
        ),
    ]
