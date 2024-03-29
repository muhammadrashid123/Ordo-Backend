from rest_framework import serializers
from rest_framework_recursive.fields import RecursiveField

from apps.accounts.models import User
from apps.audit.models import ProductParentHistory
from apps.orders.models import Product


class AuditProductSerializer(serializers.ModelSerializer):
    children = serializers.ListSerializer(child=RecursiveField())

    class Meta:
        model = Product
        fields = "__all__"


def unlink_from_parent(p: Product, user: User):
    parent = p.parent
    p.parent_id = None
    p.save(update_fields=["parent_id"])
    parent.refresh_from_db()
    ProductParentHistory.objects.create(old_parent=p.parent_id, new_parent=None, product=p.id)


def attach_to_parent(p: Product, new_parent: Product, user: User):
    old_parent = p.parent_id
    p.parent_id = new_parent.pk
    p.save(update_fields=["parent_id"])
    new_parent.refresh_from_db()
    ProductParentHistory.objects.create(old_parent=old_parent, new_parent=new_parent.pk, product=p.id)
