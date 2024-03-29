from django.contrib.postgres.search import SearchQuery
from django.db import models
from django.db.models import Q

from apps.common.utils import remove_dash_between_numerics


class ProcedureQuerySet(models.QuerySet):
    def search(self, text):
        text = remove_dash_between_numerics(text)
        return self.filter(
            Q(procedurecode__category__icontains=text) |
            Q(procedurecode__proccode=text.upper())
        )


class ProcedureManager(models.Manager):
    _queryset_class = ProcedureQuerySet

    def search(self, text):
        return self.get_queryset().search(text)
