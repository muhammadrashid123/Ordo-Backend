# Generated by Django 3.2.6 on 2022-12-22 06:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0045_auto_20221216_1510'),
    ]

    operations = [
        migrations.AddField(
            model_name='procedurecode',
            name='itemname',
            field=models.CharField(default='', max_length=256),
            preserve_default=False,
        ),
    ]
