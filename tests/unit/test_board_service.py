"""BoardService against an in-memory store.

Ways it can fail, each covered below:
- the feature is off, yet a board is created, opened or signed for;
- a guest's id changes between calls, or a forged id names a member;
- a guest gets a pass with no name, an empty one, or one the Worker refuses;
- a member's name breaks the Worker's length limit;
- the pass names the share code instead of the board, the wrong audience, a
  stale link version, or makes a non-creator the owner;
- someone other than the creator renames, resets or deletes;
- a reset keeps the old code or the old version;
- a deleted board's room is left on the Worker, or a Worker that does not
  answer undoes the deletion;
- one address asks for passes without limit;
- a guest's visit is recorded, or a member's is not;
- the sphere's old address opens a board of another sphere, or the board
  app's pass request cannot open one on any sphere.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.board import BoardService, clean_display_name
from ludamus.pacts.board import (
    BoardDeletionClaims,
    BoardDTO,
    BoardGuestDTO,
    BoardListItemDTO,
    BoardNameInvalidError,
    BoardNameRequiredError,
    BoardPassClaims,
    BoardSphereDTO,
    BoardThrottledError,
    BoardTitleInvalidError,
    BoardWorkerDTO,
    BoardWorkerUnavailableError,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.specs.board import BOARD_BOOTSTRAP_LIMIT, BOARD_SHARE_CODE_LENGTH
from tests.unit.encounter_fakes import FakeCache
from tests.unit.factories import FakeTransaction

NOW = datetime(2026, 11, 12, 18, tzinfo=UTC)
WORKER = BoardWorkerDTO(http_origin="https://board.example.com")
SPHERE = 3
CREATOR = 7
OTHER = 8


class FakeBoards:
    def __init__(self):
        self.boards: dict[int, BoardDTO] = {}
        self.visits: dict[tuple[int, int], datetime] = {}
        self.names = {CREATOR: "Ania", OTHER: "  Bartek   Nowak "}

    def create(self, *, sphere_id, creator_id, title, share_code):
        board = BoardDTO(
            pk=len(self.boards) + 1,
            sphere_id=sphere_id,
            creator_id=creator_id,
            title=title,
            share_code=share_code,
            link_version=0,
            creation_time=NOW,
        )
        self.boards[board.pk] = board
        return board

    def read_by_share_code(self, *, share_code, sphere_id):
        for board in self.boards.values():
            if board.share_code == share_code and board.sphere_id == sphere_id:
                return board
        raise NotFoundError

    def read_shared(self, share_code):
        for board in self.boards.values():
            if board.share_code == share_code:
                return board
        raise NotFoundError

    @staticmethod
    def read_sphere(sphere_id):
        return BoardSphereDTO(name=f"Sphere {sphere_id}", domain=f"s{sphere_id}.test")

    def read_owned(self, *, pk, sphere_id, creator_id):
        board = self.boards.get(pk)
        if board is None or (board.sphere_id, board.creator_id) != (
            sphere_id,
            creator_id,
        ):
            raise NotFoundError
        return board

    def rename(self, *, pk, title):
        self.boards[pk] = self.boards[pk].model_copy(update={"title": title})

    def reset_link(self, *, pk, share_code):
        board = self.boards[pk]
        self.boards[pk] = board.model_copy(
            update={"share_code": share_code, "link_version": board.link_version + 1}
        )
        return self.boards[pk]

    def delete(self, pk):
        del self.boards[pk]

    def record_visit(self, *, pk, user_id, now):
        self.visits[pk, user_id] = now

    def list_for(self, *, sphere_id, user_id):
        return [
            BoardListItemDTO(
                pk=board.pk,
                title=board.title,
                share_code=board.share_code,
                is_owner=board.creator_id == user_id,
                last_opened_at=self.visits.get((board.pk, user_id), NOW),
            )
            for board in self.boards.values()
            if board.sphere_id == sphere_id
            and (board.creator_id == user_id or (board.pk, user_id) in self.visits)
        ]

    def read_user_name(self, user_id):
        return self.names[user_id]


class ClaimsSigner:
    """Signs by keeping the claims, so a test reads what the pass says."""

    def __init__(self):
        self.signed: list[BoardPassClaims | BoardDeletionClaims] = []

    def sign(self, claims):
        self.signed.append(claims)
        return f"pass-{len(self.signed)}"


class FakeRooms:
    """The Worker's wipe: records each call, or refuses like a Worker away."""

    def __init__(self, *, confirms=True):
        self.confirms = confirms
        self.wiped: list[tuple[int, str]] = []

    def wipe(self, *, board_id, token):
        if not self.confirms:
            raise BoardWorkerUnavailableError
        self.wiped.append((board_id, token))


def _service(*, worker=WORKER, boards=None, signer=None, cache=None, rooms=None):
    return BoardService(
        transaction=FakeTransaction(),
        boards=boards if boards is not None else FakeBoards(),
        signer=signer or ClaimsSigner(),
        cache=cache or FakeCache(),
        rooms=rooms or FakeRooms(),
        worker=worker,
    )


def _bootstrap(service, board, **overrides):
    arguments = {
        "share_code": board.share_code,
        "user_id": None,
        "guest": BoardGuestDTO(),
        "requested_name": None,
        "client_ip": "203.0.113.5",
        "now": NOW,
    } | overrides
    return service.bootstrap(**arguments)


class TestAvailability:
    def test_on_with_a_board_app(self):
        assert _service().origin() == "https://board.example.com"

    def test_off_without_a_worker(self):
        service = _service(worker=None)

        assert not service.available()
        with pytest.raises(NotFoundError):
            service.create(sphere_id=SPHERE, user_id=CREATOR, title="Board")
        with pytest.raises(NotFoundError):
            service.origin()
        with pytest.raises(NotFoundError):
            service.open(share_code="x", sphere_id=SPHERE)
        with pytest.raises(NotFoundError):
            service.read_owned(pk=1, sphere_id=SPHERE, user_id=CREATOR)
        assert service.list_mine(sphere_id=SPHERE, user_id=CREATOR) == []

    def test_bootstrap_is_off_too(self):
        boards = FakeBoards()
        board = boards.create(
            sphere_id=SPHERE, creator_id=CREATOR, title="B", share_code="code"
        )

        with pytest.raises(NotFoundError):
            _bootstrap(_service(worker=None, boards=boards), board)


class TestCreate:
    def test_new_board_gets_a_long_code_and_a_tidy_title(self):
        service = _service()

        board = service.create(sphere_id=SPHERE, user_id=CREATOR, title=" Board  1 ")

        assert board.title == "Board 1"
        assert len(board.share_code) == BOARD_SHARE_CODE_LENGTH
        assert board.share_code.isalnum()

    @pytest.mark.parametrize("title", ("", "   ", "x" * 81))
    def test_unusable_title(self, title):
        with pytest.raises(BoardTitleInvalidError):
            _service().create(sphere_id=SPHERE, user_id=CREATOR, title=title)


class TestOpen:
    def test_finds_the_board_of_this_sphere_and_records_nothing(self):
        boards = FakeBoards()
        service = _service(boards=boards)
        board = service.create(sphere_id=SPHERE, user_id=CREATOR, title="B")

        assert service.open(share_code=board.share_code, sphere_id=SPHERE) == board
        assert not boards.visits

    def test_code_from_another_sphere(self):
        service = _service()
        board = service.create(sphere_id=SPHERE, user_id=CREATOR, title="B")

        with pytest.raises(NotFoundError):
            service.open(share_code=board.share_code, sphere_id=SPHERE + 1)


class TestBootstrap:
    def _board(self, service):
        return service.create(sphere_id=SPHERE, user_id=CREATOR, title="Mothership")

    def test_creator_pass(self):
        signer = ClaimsSigner()
        service = _service(signer=signer)
        board = self._board(service)

        result = _bootstrap(service, board, user_id=CREATOR)

        assert result.model_dump() == {
            "pass_token": "pass-1",
            "board_id": str(board.pk),
            "person": {"id": f"u:{CREATOR}", "name": "Ania", "owner": True},
            "title": "Mothership",
            "sphere_name": f"Sphere {SPHERE}",
            "sphere_domain": f"s{SPHERE}.test",
        }
        assert signer.signed == [
            BoardPassClaims(
                iss="ludamus",
                aud="board",
                sub=f"u:{CREATOR}",
                board=str(board.pk),
                link=0,
                name="Ania",
                owner=True,
                iat=int(NOW.timestamp()),
                exp=int((NOW + timedelta(minutes=5)).timestamp()),
            )
        ]

    def test_member_name_is_tidied_and_cut_and_body_name_ignored(self):
        boards = FakeBoards()
        boards.names[OTHER] = "Bartek " + "x" * 50
        service = _service(boards=boards)
        board = self._board(service)

        result = _bootstrap(service, board, user_id=OTHER, requested_name="Fake")

        assert result.person.name == ("Bartek " + "x" * 50)[:40]
        assert result.person.owner is False

    def test_guest_keeps_their_id_and_takes_a_new_name(self):
        service = _service()
        board = self._board(service)

        result = _bootstrap(
            service,
            board,
            guest=BoardGuestDTO(id="g:abc", name="Ania"),
            requested_name=" Ola ",
        )

        assert result.person.model_dump() == {
            "id": "g:abc",
            "name": "Ola",
            "owner": False,
        }

    def test_guest_uses_the_remembered_name(self):
        service = _service()
        board = self._board(service)

        result = _bootstrap(service, board, guest=BoardGuestDTO(id="g:abc", name="Ola"))

        assert result.person.name == "Ola"

    @pytest.mark.parametrize("forged", (None, "u:7", "7"))
    def test_guest_without_a_guest_id_gets_a_fresh_one(self, forged):
        service = _service()
        board = self._board(service)

        result = _bootstrap(service, board, guest=BoardGuestDTO(id=forged, name="Ola"))

        assert result.person.id.startswith("g:")
        assert len(result.person.id) > len("g:")

    def test_guest_without_a_name(self):
        service = _service()
        board = self._board(service)

        with pytest.raises(BoardNameRequiredError):
            _bootstrap(service, board)

    def test_remembered_name_the_worker_would_refuse(self):
        service = _service()
        board = self._board(service)

        with pytest.raises(BoardNameRequiredError):
            _bootstrap(service, board, guest=BoardGuestDTO(name="x" * 41))

    def test_new_link_version_travels_in_the_pass(self):
        signer = ClaimsSigner()
        service = _service(signer=signer)
        board = self._board(service)

        reset = service.reset_link(pk=board.pk, sphere_id=SPHERE, user_id=CREATOR)
        _bootstrap(service, reset, user_id=OTHER)

        assert signer.signed[0].link == 1

    def test_member_pass_puts_the_board_on_their_list_a_guest_pass_does_not(self):
        boards = FakeBoards()
        service = _service(boards=boards)
        board = self._board(service)

        _bootstrap(service, board, guest=BoardGuestDTO(name="Ola"))
        assert not boards.visits
        _bootstrap(service, board, user_id=OTHER)

        assert boards.visits == {(board.pk, OTHER): NOW}
        assert [
            item.pk for item in service.list_mine(sphere_id=SPHERE, user_id=OTHER)
        ] == [board.pk]

    def test_board_of_any_sphere_opens_by_its_code_and_names_its_sphere(self):
        service = _service()
        board = service.create(sphere_id=SPHERE + 1, user_id=CREATOR, title="B")

        result = _bootstrap(service, board, user_id=OTHER)

        assert (result.board_id, result.sphere_name, result.sphere_domain) == (
            str(board.pk),
            f"Sphere {SPHERE + 1}",
            f"s{SPHERE + 1}.test",
        )

    def test_unknown_code_signs_nothing(self):
        signer = ClaimsSigner()
        service = _service(signer=signer)
        self._board(service)

        with pytest.raises(NotFoundError):
            service.bootstrap(
                share_code="missing",
                user_id=OTHER,
                guest=BoardGuestDTO(),
                requested_name=None,
                client_ip="203.0.113.5",
                now=NOW,
            )
        assert not signer.signed

    def test_one_address_is_throttled_another_is_not(self):
        cache = FakeCache()
        service = _service(cache=cache)
        board = self._board(service)
        for _ in range(BOARD_BOOTSTRAP_LIMIT):
            _bootstrap(service, board, user_id=OTHER)

        with pytest.raises(BoardThrottledError):
            _bootstrap(service, board, user_id=OTHER)
        assert _bootstrap(service, board, user_id=OTHER, client_ip="198.51.100.1")
        assert _bootstrap(service, board, user_id=OTHER, now=NOW + timedelta(minutes=1))
        assert not any("203.0.113.5" in key for key in cache.entries)


class TestOwnerActions:
    def _board(self, service):
        return service.create(sphere_id=SPHERE, user_id=CREATOR, title="Before")

    def test_rename(self):
        boards = FakeBoards()
        service = _service(boards=boards)
        board = self._board(service)

        renamed = service.rename(
            pk=board.pk, sphere_id=SPHERE, user_id=CREATOR, title=" After "
        )

        assert renamed.title == boards.boards[board.pk].title == "After"

    def test_reset_link_changes_code_and_version(self):
        service = _service()
        board = self._board(service)

        reset = service.reset_link(pk=board.pk, sphere_id=SPHERE, user_id=CREATOR)

        assert reset.share_code != board.share_code
        assert reset.link_version == board.link_version + 1

    def test_delete_has_the_worker_wipe_the_room(self):
        boards, signer, rooms = FakeBoards(), ClaimsSigner(), FakeRooms()
        service = _service(boards=boards, signer=signer, rooms=rooms)
        board = self._board(service)

        wiped = service.delete(pk=board.pk, sphere_id=SPHERE, user_id=CREATOR, now=NOW)

        assert wiped
        assert not boards.boards
        assert rooms.wiped == [(board.pk, "pass-1")]
        assert signer.signed == [
            BoardDeletionClaims(
                iss="ludamus",
                aud="board-deletion",
                board=str(board.pk),
                iat=int(NOW.timestamp()),
                exp=int((NOW + timedelta(minutes=1)).timestamp()),
            )
        ]

    def test_delete_stands_when_the_worker_does_not_confirm(self):
        boards = FakeBoards()
        service = _service(boards=boards, rooms=FakeRooms(confirms=False))
        board = self._board(service)

        wiped = service.delete(pk=board.pk, sphere_id=SPHERE, user_id=CREATOR, now=NOW)

        assert not wiped
        assert not boards.boards

    @pytest.mark.parametrize(
        ("user_id", "sphere_id"), ((OTHER, SPHERE), (CREATOR, SPHERE + 1))
    )
    def test_only_the_creator_in_the_board_sphere(self, user_id, sphere_id):
        boards = FakeBoards()
        service = _service(boards=boards)
        board = self._board(service)

        with pytest.raises(NotFoundError):
            service.rename(
                pk=board.pk, sphere_id=sphere_id, user_id=user_id, title="Hijacked"
            )
        with pytest.raises(NotFoundError):
            service.reset_link(pk=board.pk, sphere_id=sphere_id, user_id=user_id)
        with pytest.raises(NotFoundError):
            service.delete(pk=board.pk, sphere_id=sphere_id, user_id=user_id, now=NOW)
        assert boards.boards == {board.pk: board}


@pytest.mark.parametrize(
    ("name", "cleaned"), (("Ania", "Ania"), ("  Ania   Kowalska ", "Ania Kowalska"))
)
def test_display_name_is_tidied(name, cleaned):
    assert clean_display_name(name) == cleaned


@pytest.mark.parametrize("name", ("", " \t ", "x" * 41, "Ania\u200b", "A\u0007"))
def test_display_name_the_worker_would_refuse(name):
    with pytest.raises(BoardNameInvalidError):
        clean_display_name(name)
