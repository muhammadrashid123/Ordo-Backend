# Generated by Django 4.2.1 on 2023-07-19 19:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0031_alter_budget_basis'),
    ]

    operations = [
        migrations.AddField(
            model_name='companymember',
            name='date_invited',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
