# Generated by Django 4.2.1 on 2023-07-23 03:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0036_alter_companymember_invite_status"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="companymemberinviteschedule",
            index=models.Index(
                condition=models.Q(("actual__isnull", True)), fields=["scheduled"], name="scheduled_actual_null"
            ),
        ),
    ]
