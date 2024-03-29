import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import User


class UserFactory(DjangoModelFactory):
    username = factory.Faker("email")

    class Meta:
        model = User


class AdminUserFactory(UserFactory):
    is_staff = True
