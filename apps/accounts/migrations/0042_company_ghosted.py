# Generated by Django 4.2.1 on 2023-07-28 02:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0041_alter_companymember_office'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='ghosted',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
