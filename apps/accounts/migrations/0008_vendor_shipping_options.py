# Generated by Django 3.2.6 on 2022-03-31 15:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_vendorrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendor',
            name='shipping_options',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
