from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, Track
from ludamus.pacts import EventDTO
from ludamus.pacts.event import (
    ConfirmationDashboardDTO,
    ConfirmationEmailGroupDTO,
    ConfirmationFacilitatorDTO,
    ConfirmationOrganizerRowDTO,
    ConfirmationSessionDTO,
    ConfirmationStatusGroupDTO,
    ConfirmationTrackRowDTO,
    ConfirmationTrackViewDTO,
)
from ludamus.pacts.legacy import TrackDTO
from tests.integration.conftest import AgendaItemFactory, SessionFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import timetable_tab_urls

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _stats(**overrides):
    return {
        "hosts_count": 0,
        "pending_proposals": 0,
        "rooms_count": 0,
        "scheduled_sessions": 0,
        "total_proposals": 0,
        "total_sessions": 0,
    } | overrides


def _empty_dashboard(**overrides):
    return ConfirmationDashboardDTO(
        **{
            "organizers": [],
            "tracks": [],
            "scheduled_count": 0,
            "confirmed_count": 0,
            "progress_pct": 0,
            "claimed_facilitator_count": 0,
            "unclaimed_facilitator_count": 0,
            "without_facilitator_count": 0,
        }
        | overrides
    )


def _empty_track_view(**overrides):
    return ConfirmationTrackViewDTO(
        **{
            "facilitators": [],
            "facilitator_count": 0,
            "unclaimed_facilitator_count": 0,
            "scheduled_count": 0,
            "confirmed_count": 0,
            "progress_pct": 0,
            "without_facilitator_count": 0,
        }
        | overrides
    )


def _session_dto(session, item=None, **overrides):
    return ConfirmationSessionDTO(
        **{
            "session_pk": session.pk,
            "title": session.title,
            "category_name": session.category.name,
            "room_name": item.space.name if item else "",
            "start_time": item.start_time if item else None,
            "end_time": item.end_time if item else None,
            "agenda_item_pk": item.pk if item else None,
            "is_confirmed": bool(item and item.session_confirmed),
            "co_facilitator_names": [],
            "other_track_names": [],
        }
        | overrides
    )


class TestConfirmationsPageView:
    """Tests for /panel/event/<slug>/timetable/confirmations/."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})

    @classmethod
    def expected_context(cls, event, **overrides):
        return {
            "current_event": EventDTO.model_validate(event),
            "events": [EventDTO.model_validate(event)],
            "is_proposal_active": False,
            "stats": _stats(),
            "active_nav": "timetable",
            "all_tracks": [],
            "managed_track_pks": set(),
            "filter_track_pk": None,
            "dashboard": _empty_dashboard(),
            "track_view": None,
            "slug": event.slug,
            "next_url": cls.get_url(event),
            "tab_urls": timetable_tab_urls(event),
            "active_tab": "confirmations",
        } | overrides

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirmations", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_ok_returns_empty_dashboard(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(event),
        )

    def test_counts_confirmed_of_scheduled_per_organizer_and_track(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        track.managers.add(active_user)
        mine = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        unclaimed = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben"
        )
        for facilitator, confirmed in ((mine, True), (mine, False), (unclaimed, False)):
            session = SessionFactory(category=proposal_category, status="accepted")
            session.facilitators.add(facilitator)
            session.tracks.add(track)
            AgendaItemFactory(session=session, session_confirmed=confirmed)

        # `?track=` empty keeps the event-wide dashboard: a manager of exactly
        # one track would otherwise land straight on that track's list.
        url = f"{self.get_url(event)}?track="
        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=3,
                    scheduled_sessions=3,
                    total_proposals=3,
                    total_sessions=3,
                ),
                all_tracks=[TrackDTO.model_validate(track)],
                managed_track_pks={track.pk},
                next_url=url,
                dashboard=_empty_dashboard(
                    organizers=[
                        ConfirmationOrganizerRowDTO(
                            organizer_id=None,
                            organizer_name="",
                            facilitator_count=1,
                            scheduled_count=1,
                            confirmed_count=0,
                            progress_pct=0,
                        ),
                        ConfirmationOrganizerRowDTO(
                            organizer_id=active_user.pk,
                            organizer_name=active_user.name,
                            facilitator_count=1,
                            scheduled_count=2,
                            confirmed_count=1,
                            progress_pct=50,
                        ),
                    ],
                    tracks=[
                        ConfirmationTrackRowDTO(
                            track_pk=track.pk,
                            track_name="RPG",
                            manager_names=[active_user.name],
                            facilitator_count=2,
                            scheduled_count=3,
                            confirmed_count=1,
                            progress_pct=33,
                        )
                    ],
                    scheduled_count=3,
                    confirmed_count=1,
                    progress_pct=33,
                    claimed_facilitator_count=1,
                    unclaimed_facilitator_count=1,
                ),
            ),
        )

    def test_totals_count_a_co_facilitated_item_once(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        other_organizer = UserFactory(username="other-organizer", name="Zoe Other")
        mine = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        theirs = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben", organizer=other_organizer
        )
        session = SessionFactory(category=proposal_category, status="accepted")
        session.facilitators.add(mine, theirs)
        AgendaItemFactory(session=session, session_confirmed=True)

        response = authenticated_client.get(self.get_url(event))

        # Both organizer rows report the item, each correctly. Adding the rows
        # up would report two program items where the event has one.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=1,
                    scheduled_sessions=1,
                    total_proposals=1,
                    total_sessions=1,
                ),
                dashboard=_empty_dashboard(
                    organizers=[
                        ConfirmationOrganizerRowDTO(
                            organizer_id=active_user.pk,
                            organizer_name=active_user.name,
                            facilitator_count=1,
                            scheduled_count=1,
                            confirmed_count=1,
                            progress_pct=100,
                        ),
                        ConfirmationOrganizerRowDTO(
                            organizer_id=other_organizer.pk,
                            organizer_name="Zoe Other",
                            facilitator_count=1,
                            scheduled_count=1,
                            confirmed_count=1,
                            progress_pct=100,
                        ),
                    ],
                    scheduled_count=1,
                    confirmed_count=1,
                    progress_pct=100,
                    claimed_facilitator_count=2,
                ),
            ),
        )

    def test_reports_scheduled_sessions_that_have_no_facilitator(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = SessionFactory(category=proposal_category, status="accepted")
        AgendaItemFactory(session=session)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=1,
                    scheduled_sessions=1,
                    total_proposals=1,
                    total_sessions=1,
                ),
                dashboard=_empty_dashboard(
                    scheduled_count=1, without_facilitator_count=1
                ),
            ),
        )

    def test_selecting_a_track_keeps_it_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )

        url = f"{self.get_url(event)}?track={track.pk}"
        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
                dashboard=None,
                track_view=_empty_track_view(),
                next_url=url,
            ),
        )

    def test_auto_selects_the_single_track_the_user_manages(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        track.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                all_tracks=[TrackDTO.model_validate(track)],
                managed_track_pks={track.pk},
                filter_track_pk=track.pk,
                dashboard=None,
                track_view=_empty_track_view(),
            ),
        )

    def test_track_view_lists_only_facilitators_scheduled_in_that_track(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        other = Track.objects.create(
            event=event, name="Talks", slug="talks", is_public=True
        )
        listed = Facilitator.objects.create(event=event, display_name="Ada", slug="ada")
        elsewhere = Facilitator.objects.create(
            event=event, display_name="Ben", slug="ben"
        )
        items = {}
        for facilitator, session_track in ((listed, track), (elsewhere, other)):
            session = SessionFactory(category=proposal_category, status="accepted")
            session.facilitators.add(facilitator)
            session.tracks.add(session_track)
            items[facilitator.pk] = AgendaItemFactory(session=session)

        url = f"{self.get_url(event)}?track={track.pk}"
        response = authenticated_client.get(url)

        item = items[listed.pk]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=2,
                    scheduled_sessions=2,
                    total_proposals=2,
                    total_sessions=2,
                ),
                all_tracks=[
                    TrackDTO.model_validate(track),
                    TrackDTO.model_validate(other),
                ],
                filter_track_pk=track.pk,
                dashboard=None,
                next_url=url,
                track_view=ConfirmationTrackViewDTO(
                    facilitators=[
                        ConfirmationFacilitatorDTO(
                            display_name="Ada",
                            organizer_name="",
                            organizer_id=None,
                            pk=listed.pk,
                            slug="ada",
                            email_groups=[
                                ConfirmationEmailGroupDTO(
                                    contact_email=item.session.contact_email,
                                    status_groups=[
                                        ConfirmationStatusGroupDTO(
                                            status="scheduled",
                                            sessions=[_session_dto(item.session, item)],
                                        )
                                    ],
                                    confirmable_count=1,
                                )
                            ],
                            scheduled_count=1,
                            confirmed_count=0,
                            unplaced_count=0,
                            pending_count=0,
                            is_fully_confirmed=False,
                        )
                    ],
                    facilitator_count=1,
                    unclaimed_facilitator_count=1,
                    scheduled_count=1,
                    confirmed_count=0,
                    progress_pct=0,
                    without_facilitator_count=0,
                ),
            ),
        )

    def test_track_view_groups_a_facilitators_program(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        scheduled = SessionFactory(
            category=proposal_category,
            status="accepted",
            title="Dragons",
            contact_email="ada@example.com",
        )
        scheduled.facilitators.add(facilitator)
        scheduled.tracks.add(track)
        item = AgendaItemFactory(session=scheduled, session_confirmed=True)
        for title, status in (("Later", "accepted"), ("Idea", "pending")):
            counted = SessionFactory(
                category=proposal_category,
                status=status,
                title=title,
                contact_email="ada@example.com",
            )
            counted.facilitators.add(facilitator)
            counted.tracks.add(track)
        on_hold = SessionFactory(
            category=proposal_category,
            status="on_hold",
            title="Maybe",
            contact_email="ada@example.com",
        )
        on_hold.facilitators.add(facilitator)
        on_hold.tracks.add(track)

        url = f"{self.get_url(event)}?track={track.pk}"
        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=4,
                    pending_proposals=1,
                    scheduled_sessions=1,
                    total_proposals=4,
                    total_sessions=2,
                ),
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
                dashboard=None,
                next_url=url,
                track_view=ConfirmationTrackViewDTO(
                    facilitators=[
                        ConfirmationFacilitatorDTO(
                            display_name="Ada",
                            organizer_name=active_user.name,
                            organizer_id=active_user.pk,
                            pk=facilitator.pk,
                            slug="ada",
                            email_groups=[
                                ConfirmationEmailGroupDTO(
                                    contact_email="ada@example.com",
                                    status_groups=[
                                        ConfirmationStatusGroupDTO(
                                            status="scheduled",
                                            sessions=[_session_dto(scheduled, item)],
                                        ),
                                        ConfirmationStatusGroupDTO(
                                            status="on_hold",
                                            sessions=[_session_dto(on_hold)],
                                        ),
                                    ],
                                    confirmable_count=1,
                                )
                            ],
                            scheduled_count=1,
                            confirmed_count=1,
                            unplaced_count=1,
                            pending_count=1,
                            is_fully_confirmed=True,
                        )
                    ],
                    facilitator_count=1,
                    unclaimed_facilitator_count=0,
                    scheduled_count=1,
                    confirmed_count=1,
                    progress_pct=100,
                    without_facilitator_count=0,
                ),
            ),
        )

    def test_track_view_is_empty_when_nothing_is_scheduled_in_the_track(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        track = Track.objects.create(
            event=event, name="RPG", slug="rpg", is_public=True
        )

        url = f"{self.get_url(event)}?track={track.pk}"
        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                all_tracks=[TrackDTO.model_validate(track)],
                filter_track_pk=track.pk,
                dashboard=None,
                track_view=_empty_track_view(),
                next_url=url,
            ),
        )

    def test_unconfirmed_agenda_item_is_not_counted_as_confirmed(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Ada", slug="ada", organizer=active_user
        )
        session = SessionFactory(category=proposal_category, status="accepted")
        session.facilitators.add(facilitator)
        AgendaItemFactory(session=session, session_confirmed=False)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/timetable-confirmations.html",
            context_data=self.expected_context(
                event,
                stats=_stats(
                    hosts_count=1,
                    scheduled_sessions=1,
                    total_proposals=1,
                    total_sessions=1,
                ),
                dashboard=_empty_dashboard(
                    organizers=[
                        ConfirmationOrganizerRowDTO(
                            organizer_id=active_user.pk,
                            organizer_name=active_user.name,
                            facilitator_count=1,
                            scheduled_count=1,
                            confirmed_count=0,
                            progress_pct=0,
                        )
                    ],
                    scheduled_count=1,
                    confirmed_count=0,
                    claimed_facilitator_count=1,
                ),
            ),
        )
