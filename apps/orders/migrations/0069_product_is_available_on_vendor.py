# Generated by Django 4.1.6 on 2023-04-06 23:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0068_alter_procedure_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_available_on_vendor',
            field=models.BooleanField(default=True),
        ),
    ]
