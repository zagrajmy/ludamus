import factory
from django.contrib.auth.hashers import make_password
from factory.django import DjangoModelFactory

from ludamus.adapters.db.django.models import User
from ludamus.pacts.crowd import UserType


class CompleteUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Faker("name")
    password = factory.LazyFunction(lambda: make_password(None))
    user_type = UserType.ACTIVE
    username = factory.Faker("uuid4")


class AnonymousUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    is_active = False
    password = factory.LazyFunction(lambda: make_password(None))
    slug = factory.Sequence(lambda n: f"code_{n}")
    user_type = UserType.ANONYMOUS
    username = factory.Faker("uuid4")
