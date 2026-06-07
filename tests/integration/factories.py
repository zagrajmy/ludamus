import factory
from django.contrib.auth.hashers import make_password
from factory.django import DjangoModelFactory
from faker import Faker

from ludamus.adapters.db.django.models import User
from ludamus.pacts import UserType

faker = Faker()


class CompleteUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Faker("email")
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
