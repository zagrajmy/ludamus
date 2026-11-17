import pytest
from pydantic import ValidationError

from ludamus.pacts.parley import ParleyRoomDTO, ParleyRoomKind


def test_a_room_listed_only_to_moderate_it_must_be_moderated():
    with pytest.raises(ValidationError, match="must be moderated"):
        ParleyRoomDTO(
            kind=ParleyRoomKind.SESSION,
            sphere_id=1,
            pk=2,
            title="Mothership",
            can_write=True,
            can_moderate=False,
            moderating=True,
        )
