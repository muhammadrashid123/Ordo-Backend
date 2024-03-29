import uuid

from django.db import models

from apps.accounts.models import User


class ProductParentHistory(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4)
    product = models.IntegerField()
    old_parent = models.IntegerField(null=True)
    new_parent = models.IntegerField(null=True)


class RollbackInformation(models.Model):
    operation_id = models.UUIDField(help_text="Apply operation ID")
    max_parent_id_before = models.IntegerField(help_text="Maximum id of existing parent before operation started")
    last_inserted_parent_id = models.IntegerField(help_text="Last inserted parent id", null=True)


class SearchHistory(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    query = models.CharField(max_length=1024)
    user = models.ForeignKey(User, on_delete=models.PROTECT)


class BadImageUrl(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    image_url = models.URLField(max_length=1024)
    user = models.ForeignKey(User, on_delete=models.PROTECT)


class OrderTasks(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    task_id = models.UUIDField()
    order_id = models.IntegerField()
