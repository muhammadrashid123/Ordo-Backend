# Generated by Django 4.2.1 on 2024-02-23 07:44

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0096_priceage'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='cart',
            unique_together=set(),
        ),
    ]
