"""Integration tests for the panel lists' spreadsheet exports."""

from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus
from io import BytesIO

from django.urls import reverse
from django.utils import timezone
from odf import teletype
from odf.opendocument import load
from odf.table import Table, TableCell, TableRow

from ludamus.gates.web.django.chronology.panel.views.columns import PanelColumnView
from ludamus.gates.web.django.chronology.panel.views.export import ODS_CONTENT_TYPE
from ludamus.gates.web.django.pagination import DEFAULT_PAGE_SIZE
from ludamus.links.db.django.models import (
    Discount,
    EventPanelSettings,
    Facilitator,
    Guild,
    GuildMembership,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldValue,
    Track,
)
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import (
    assert_login_required,
    assert_response,
    assert_response_404,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
    schedule_session,
)

_PROPOSAL_KEYS = ["title", "host", "category", "status", "created"]
_PROPOSAL_LABELS = {
    "title": "Title",
    "host": "Presenter name",
    "category": "Category",
    "status": "Status",
    "created": "Created",
    "scheduled": "Scheduled",
}
_FACILITATOR_KEYS = [
    "name",
    "linked",
    "guild",
    "sessions",
    "accreditation",
    "organizer",
]
_FACILITATOR_LABELS = {
    "name": "Display Name",
    "linked": "Linked User",
    "guild": "Guild",
    "sessions": "Sessions",
    "accreditation": "Accreditation",
    "organizer": "Organizer",
    "scheduled_sessions": "Scheduled sessions",
    "scheduled_hours": "Scheduled hours",
    "discount_kind": "Discount kind",
    "discount_value": "Discount value",
    "discount_note": "Note",
}
_PROPOSAL_HEADERS = [_PROPOSAL_LABELS[key] for key in _PROPOSAL_KEYS]
_FACILITATOR_HEADERS = [_FACILITATOR_LABELS[key] for key in _FACILITATOR_KEYS]
_EMPTY_SELECTION_ERROR = "Pick at least one column to export."


def _columns(labels, keys):
    # Every export cell is text, the badge and the guild mark included.
    return [PanelColumnView(key=key, label=labels[key], kind="text") for key in keys]


def _sheet(response):
    (table,) = load(BytesIO(response.content)).spreadsheet.getElementsByType(Table)
    return [
        [teletype.extractText(cell) for cell in row.getElementsByType(TableCell)]
        for row in table.getElementsByType(TableRow)
    ]


def _formulas(response):
    document = load(BytesIO(response.content))
    return [
        cell.getAttribute("formula") for cell in document.getElementsByType(TableCell)
    ]


def _assert_download(response, *, event, part):
    assert_response(response, HTTPStatus.OK)
    assert response["Content-Type"] == ODS_CONTENT_TYPE
    filename = f"{event.slug}-{part}-{timezone.localdate()}.ods"
    assert response["Content-Disposition"] == f'attachment; filename="{filename}"'


def _category(event):
    return ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")


def _proposal(event, category, *, title="Dragon Heist", slug="dragon-heist", **kwargs):
    return Session.objects.create(
        event=event,
        category=category,
        facilitator_name="Host",
        title=title,
        slug=slug,
        participants_limit=5,
        **({"status": "pending"} | kwargs),
    )


def _proposal_tab_urls(event):
    return {
        "list": reverse("panel:proposals", kwargs={"slug": event.slug}),
        "columns": reverse("panel:proposal-columns", kwargs={"slug": event.slug}),
        "export": reverse("panel:proposal-export", kwargs={"slug": event.slug}),
    }


class TestProposalExportPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:proposal-export", kwargs={"slug": event.slug})

    def _chooser_context(self, event, *, hidden_params, error):
        return {
            **panel_context(event, active_nav="proposals"),
            "active_tab": "export",
            "tab_urls": _proposal_tab_urls(event),
            "chosen_columns": _columns(_PROPOSAL_LABELS, _PROPOSAL_KEYS),
            "available_columns": _columns(_PROPOSAL_LABELS, ["scheduled"]),
            "hidden_params": hidden_params,
            "error": error,
        }

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_not_a_manager(response)

    def test_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:proposal-export", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_chooser_preselects_the_lists_columns_and_keeps_the_filters(
        self, panel_client, event
    ):
        response = panel_client.get(self._url(event), {"status": "all", "search": "x"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-export.html",
            context_data=self._chooser_context(
                event, hidden_params=[("status", "all"), ("search", "x")], error=None
            ),
        )

    def test_ticking_nothing_re_renders_with_an_error(self, panel_client, event):
        response = panel_client.get(self._url(event), {"columns": ["", "bogus"]})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-export.html",
            context_data=self._chooser_context(
                event, hidden_params=[], error=_EMPTY_SELECTION_ERROR
            ),
        )

    def test_downloads_every_matching_row_across_pages(self, panel_client, event):
        category = _category(event)
        count = DEFAULT_PAGE_SIZE + 5
        for index in range(count):
            _proposal(event, category, title=f"Session {index}", slug=f"s-{index}")
        _proposal(event, category, title="Rejected", slug="rejected", status="rejected")

        response = panel_client.get(
            self._url(event), {"status": "pending", "columns": _PROPOSAL_KEYS}
        )

        _assert_download(response, event=event, part="proposals")
        rows = _sheet(response)
        assert rows[0] == _PROPOSAL_HEADERS
        assert len(rows) == count + 1
        assert sorted(row[0] for row in rows[1:]) == sorted(
            f"Session {index}" for index in range(count)
        )
        # The badge and the localized date the list renders itself arrive as text.
        assert {tuple(row[1:]) for row in rows[1:]} == {
            ("Host", "RPG", "Pending", str(timezone.localdate()))
        }

    def test_scheduled_column_reads_yes_or_no(self, panel_client, event):
        category = _category(event)
        placed = _proposal(event, category, title="Placed", slug="placed")
        _proposal(event, category, title="Waiting", slug="waiting")
        schedule_session(
            session=placed, space=SpaceFactory(event=event), start=event.start_time
        )

        response = panel_client.get(
            self._url(event), {"columns": ["title", "scheduled"], "status": "all"}
        )

        _assert_download(response, event=event, part="proposals")
        header, *rows = _sheet(response)
        assert header == ["Title", "Scheduled"]
        assert sorted(rows) == [["Placed", "Yes"], ["Waiting", "No"]]

    def test_formula_looking_title_stays_text(self, panel_client, event):
        _proposal(event, _category(event), title="=SUM(A1:A9)", slug="sum")

        response = panel_client.get(self._url(event), {"columns": ["title"]})

        _assert_download(response, event=event, part="proposals")
        assert _sheet(response) == [["Title"], ["=SUM(A1:A9)"]]
        assert set(_formulas(response)) == {None}

    def test_multiline_field_value_keeps_its_line_break(self, panel_client, event):
        field = SessionField.objects.create(
            event=event,
            name="Description",
            question="Describe it",
            slug="description",
            field_type="text",
            order=0,
        )
        session = _proposal(event, _category(event))
        SessionFieldValue.objects.create(
            session=session, field=field, value="First line\nSecond line"
        )

        response = panel_client.get(
            self._url(event), {"columns": ["title", f"field_{field.pk}"]}
        )

        _assert_download(response, event=event, part="proposals")
        assert _sheet(response) == [
            ["Title", "Description"],
            ["Dragon Heist", "First line\nSecond line"],
        ]

    def test_foreign_field_key_is_dropped(self, panel_client, sphere, event):
        foreign = SessionField.objects.create(
            event=EventFactory(sphere=sphere),
            name="Secret",
            question="?",
            slug="secret",
            field_type="text",
            order=0,
        )
        _proposal(event, _category(event))

        response = panel_client.get(
            self._url(event), {"columns": ["title", f"field_{foreign.pk}"]}
        )

        _assert_download(response, event=event, part="proposals")
        assert _sheet(response) == [["Title"], ["Dragon Heist"]]

    def test_no_match_still_downloads_the_header_row(self, panel_client, event):
        _proposal(event, _category(event), status="rejected")

        response = panel_client.get(self._url(event), {"columns": _PROPOSAL_KEYS})

        _assert_download(response, event=event, part="proposals")
        assert _sheet(response) == [_PROPOSAL_HEADERS]

    def test_foreign_track_is_not_found(self, panel_client, sphere, event):
        _proposal(event, _category(event))
        track = Track.objects.create(
            event=EventFactory(sphere=sphere), name="Other", slug="other"
        )

        response = panel_client.get(
            self._url(event), {"track": str(track.pk), "columns": ["title"]}
        )

        assert_response_404(response)


def _facilitator(event, name, **kwargs):
    return Facilitator.objects.create(
        event=event, display_name=name, slug=name.lower(), user=None, **kwargs
    )


def _facilitator_tab_urls(event):
    return {
        "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
        "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
        "columns": reverse("panel:facilitator-columns", kwargs={"slug": event.slug}),
        "export": reverse("panel:facilitator-export", kwargs={"slug": event.slug}),
        "bin": reverse("panel:facilitator-bin", kwargs={"slug": event.slug}),
    }


_FACILITATOR_EXPORT_ONLY = [
    "scheduled_sessions",
    "scheduled_hours",
    "discount_kind",
    "discount_value",
    "discount_note",
]


class TestFacilitatorExportPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:facilitator-export", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_not_a_manager(response)

    def test_chooser_offers_export_only_columns_once(self, panel_client, event):
        EventPanelSettings.objects.create(
            event=event, facilitator_columns=["name", "guild"]
        )

        response = panel_client.get(self._url(event), {"accreditation": "guest"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-export.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "active_tab": "export",
                "tab_urls": _facilitator_tab_urls(event),
                "chosen_columns": _columns(_FACILITATOR_LABELS, ["name", "guild"]),
                "available_columns": _columns(
                    _FACILITATOR_LABELS,
                    [
                        "linked",
                        "sessions",
                        "accreditation",
                        "organizer",
                        *_FACILITATOR_EXPORT_ONLY,
                    ],
                ),
                "hidden_params": [("accreditation", "guest")],
                "error": None,
            },
        )

    def test_downloads_every_matching_row_across_pages(self, panel_client, event):
        count = DEFAULT_PAGE_SIZE + 5
        for index in range(count):
            _facilitator(event, f"Person{index:02d}")

        response = panel_client.get(self._url(event), {"columns": _FACILITATOR_KEYS})

        _assert_download(response, event=event, part="facilitators")
        rows = _sheet(response)
        assert rows[0] == _FACILITATOR_HEADERS
        assert [row[0] for row in rows[1:]] == [
            f"Person{index:02d}" for index in range(count)
        ]
        assert {tuple(row[1:]) for row in rows[1:]} == {("None", "", "0", "None", "—")}

    def test_accreditation_and_organizer_filters_narrow_the_rows(
        self, panel_client, active_user, event
    ):
        _facilitator(event, "Mine", accreditation_type="guest", organizer=active_user)
        _facilitator(
            event, "Theirs", accreditation_type="guest", organizer=UserFactory()
        )
        _facilitator(event, "Plain", accreditation_type="none", organizer=active_user)

        response = panel_client.get(
            self._url(event),
            {
                "accreditation": "guest",
                "organizer": "mine",
                "columns": _FACILITATOR_KEYS,
            },
        )

        _assert_download(response, event=event, part="facilitators")
        assert _sheet(response) == [
            _FACILITATOR_HEADERS,
            ["Mine", "None", "", "0", "Guest", active_user.name],
        ]

    def test_guild_column_arrives_as_the_guild_name(self, panel_client, event):
        member = UserFactory()
        guild = Guild.objects.create(sphere=event.sphere, name="Topory", slug="topory")
        GuildMembership.objects.create(sphere=event.sphere, guild=guild, member=member)
        Facilitator.objects.create(
            event=event, display_name="Hanna", slug="hanna", user=member
        )

        response = panel_client.get(self._url(event), {"columns": ["name", "guild"]})

        _assert_download(response, event=event, part="facilitators")
        assert _sheet(response) == [["Display Name", "Guild"], ["Hanna", "Topory"]]

    def test_discount_and_schedule_columns_come_from_their_sources(
        self, panel_client, event
    ):
        busy = _facilitator(event, "Busy")
        _facilitator(event, "Idle")
        Discount.objects.create(
            event=event,
            facilitator=busy,
            kind="percent",
            value=Decimal("15.00"),
            note="VIP",
        )
        space = SpaceFactory(event=event)
        for index, hours in enumerate((1, 0.5)):
            session = SessionFactory(
                category=ProposalCategoryFactory(event=event),
                event=event,
                status="accepted",
            )
            session.facilitators.add(busy)
            schedule_session(
                session=session,
                space=space,
                start=event.start_time + timedelta(hours=index * 2),
                hours=hours,
            )

        response = panel_client.get(
            self._url(event), {"columns": ["name", *_FACILITATOR_EXPORT_ONLY]}
        )

        _assert_download(response, event=event, part="facilitators")
        assert _sheet(response) == [
            [
                "Display Name",
                "Scheduled sessions",
                "Scheduled hours",
                "Discount kind",
                "Discount value",
                "Note",
            ],
            ["Busy", "2", "1.5", "Percent", "15.00", "VIP"],
            ["Idle", "", "", "", "", ""],
        ]

    def test_ticking_nothing_re_renders_with_an_error(self, panel_client, event):
        response = panel_client.get(self._url(event), {"columns": [""]})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-export.html",
            context_data={
                **panel_context(event, active_nav="facilitators"),
                "active_tab": "export",
                "tab_urls": _facilitator_tab_urls(event),
                "chosen_columns": _columns(_FACILITATOR_LABELS, _FACILITATOR_KEYS),
                "available_columns": _columns(
                    _FACILITATOR_LABELS, _FACILITATOR_EXPORT_ONLY
                ),
                "hidden_params": [],
                "error": _EMPTY_SELECTION_ERROR,
            },
        )
