import random

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from ..common.month import Month
from . import models as m
from .models import BUILTIN_BUDGET_SLUGS, BasisType


class UserFactory(DjangoModelFactory):
    class Meta:
        model = m.User

    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    username = factory.LazyAttribute(lambda o: o.email)
    email = factory.LazyAttribute(lambda o: f"{o.first_name}.{o.last_name}@example.com")


class CompanyFactory(DjangoModelFactory):
    name = factory.Faker("company")

    class Meta:
        model = m.Company


class VendorFactory(DjangoModelFactory):
    class Meta:
        model = m.Vendor


class OpenDentalKeyFactory(DjangoModelFactory):
    class Meta:
        model = m.OpenDentalKey

    key = factory.Faker("pystr")


class OfficeFactory(DjangoModelFactory):
    class Meta:
        model = m.Office

    company = factory.SubFactory(CompanyFactory)
    dental_api = factory.SubFactory(OpenDentalKeyFactory)


class OfficeVendorFactory(DjangoModelFactory):
    class Meta:
        model = m.OfficeVendor

    vendor = factory.SubFactory(VendorFactory)
    office = factory.SubFactory(OfficeFactory)


def get_current_month():
    current_date = timezone.localdate()
    month = Month.from_date(current_date)
    return month


class BudgetFactory(DjangoModelFactory):
    class Meta:
        model = m.Budget

    office = factory.SubFactory(OfficeFactory)
    month = factory.LazyFunction(get_current_month)
    adjusted_production = factory.Faker("pydecimal", min_value=30, max_value=120, right_digits=2)
    collection = factory.Faker("pydecimal", min_value=30, max_value=120, right_digits=2)
    basis = BasisType.PRODUCTION

    @factory.post_generation
    def create_subaccounts(obj, create, extracted, **kwargs):
        if not create:
            return
        for slug in BUILTIN_BUDGET_SLUGS:
            SubaccountFactory(budget=obj, slug=slug, name=slug.capitalize(), percentage=5, spend=0)


class SubaccountFactory(DjangoModelFactory):
    class Meta:
        model = m.Subaccount

    budget = factory.SubFactory(BudgetFactory)
    slug = "dental"
    percentage = 5
    spend = 0


class OfficeBudgetFactory(DjangoModelFactory):
    class Meta:
        model = m.OfficeBudget
        exclude = ["budget_type"]

    budget_type = factory.LazyFunction(lambda: random.choice(m.BudgetType.choices)[0])

    dental_budget_type = factory.LazyAttribute(lambda o: o.budget_type)
    dental_total_budget = factory.Faker("pydecimal", min_value=20000, max_value=100000)
    dental_percentage = factory.Faker("pydecimal", min_value=3, max_value=10)

    dental_budget = factory.LazyAttribute(lambda o: o.dental_total_budget * o.dental_percentage / 100)
    dental_spend = factory.Faker("pydecimal", min_value=30, max_value=120)

    adjusted_production = factory.Faker("pydecimal", min_value=30, max_value=120)
    collection = factory.Faker("pydecimal", min_value=30, max_value=120)

    # office_* is used for managing budgets for amazon
    office_budget_type = factory.LazyAttribute(lambda o: o.budget_type)
    office_total_budget = factory.Faker("pydecimal", min_value=20000, max_value=100000)
    office_percentage = factory.Faker("pydecimal", min_value=3, max_value=10)
    office_budget = factory.LazyAttribute(lambda o: o.office_total_budget * o.office_percentage / 100)
    office_spend = factory.Faker("pydecimal", min_value=30, max_value=120)

    miscellaneous_spend = factory.Faker("pydecimal", min_value=0, max_value=1000)

    month = factory.LazyFunction(get_current_month)


class CompanyMemberFactory(DjangoModelFactory):
    class Meta:
        model = m.CompanyMember

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(UserFactory)
    office = factory.LazyAttribute(lambda o: OfficeFactory(company=o.company))
    token = factory.Faker("pystr")
    email = factory.Faker("email")


class SubscriptionFactory(DjangoModelFactory):
    class Meta:
        model = m.Subscription

    office = factory.SubFactory(OfficeFactory)
