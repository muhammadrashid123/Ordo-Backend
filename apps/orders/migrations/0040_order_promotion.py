
import django.db.models.deletion
import django_extensions.db.fields
from django.conf import settings
from django.db import migrations, models

import apps.common.models


class Migration(migrations.Migration):
    
    dependencies = [
        ('orders', '0039_product_sku'),
    ]

    operations = [
        migrations.CreateModel(
            name='Promotion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=128, unique=True)),
                ('type', models.IntegerField(default=1)),
                ('reduction_price', models.IntegerField(default=0, null=True)),
                ('description', models.CharField(max_length=128, null=True)),
            ],
        ),
    ]
