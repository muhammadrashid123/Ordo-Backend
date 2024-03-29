from django.contrib.postgres.search import TrigramWordSimilarity
from django.db import models
from django.db.models import Q
from django.db.models.expressions import Case, RawSQL, When

from apps.common.enums import SupportedVendor


class ProductQuerySet(models.QuerySet):
    def search(self, text):
        # this is for search for henry schein product id
        # text = remove_dash_between_numerics(text)
        # tws = TrigramWordSimilarity(text, "words__words")
        # q = SearchQuery(text, config="english")
        # .filter(Q(search_vector=q))
        return self.filter(
            Q(words__words__trigram_word_similar=text)
            | Q(words__numbers__overlap=[text])
            | Q(words__names__overlap=[text])
        ).annotate(
            relevance=Case(
                When(words__numbers__overlap=[text], then=1.0),
                When(words__names__overlap=[text], then=1.0),
                default=TrigramWordSimilarity(text, "words__words"),
                output_field=models.FloatField(),
            )
        )

    def with_inventory_refs(self):
        return self.annotate(_inventory_refs=RawSQL("inventory_refs", (), output_field=models.IntegerField()))


class ProductManager(models.Manager):
    _queryset_class = ProductQuerySet

    def get_queryset(self):
        return super().get_queryset().exclude(is_manual=True)

    def search(self, text):
        return self.get_queryset().search(text)

    def available_products(self):
        return self.get_queryset().filter(is_available_on_vendor=True)

    def unavailable_products(self):
        return self.get_queryset().filter(is_available_on_vendor=False)

    async def avalues_list(self, field):
        return await self.get_queryset().avalues_list(field)


class Net32ProductManager(ProductManager):
    def get_queryset(self):
        return super().get_queryset().filter(vendor__slug=SupportedVendor.Net32.value)
