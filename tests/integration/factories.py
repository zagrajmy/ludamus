import factory
from django.contrib.auth.hashers import make_password
from factory.django import DjangoModelFactory

from ludamus.links.db.django.models import User
from ludamus.pacts import OrganizerFieldDTO, OrganizerFieldOptionDTO
from ludamus.pacts.crowd import UserType


class CompleteUserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    email_verified = True
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


RPG_OPTION = OrganizerFieldOptionDTO(label="RPG", order=1, pk=1, value="rpg")
BOARD_OPTION = OrganizerFieldOptionDTO(label="Board", order=0, pk=2, value="board")


def organizer_field_dto(**overrides) -> OrganizerFieldDTO:
    defaults = {
        "field_type": "select",
        "name": "Tags",
        "options": [RPG_OPTION, BOARD_OPTION],
        "order": 0,
        "pk": 1,
        "question": "What tags apply?",
        "slug": "tags",
    }
    return OrganizerFieldDTO(**(defaults | overrides))
