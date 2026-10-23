"""Repository for reports of illegal content.

Each reportable kind has a resolver that finds the content only where the
reporting sphere shows it publicly, so an id from a hidden event or another
sphere names nothing. A new kind needs a resolver here and a model in
`_MODELS`; the report table stays as it is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.urls import reverse

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.models import ContentReport, Session, Sphere, User
from ludamus.pacts.ids import UserId
from ludamus.pacts.legacy import EventVisibility
from ludamus.pacts.report import (
    ContentReportDTO,
    ReportedContentKind,
    ReporterContactDTO,
    ReportReason,
    ReportRepositoryProtocol,
    ReportStatus,
    ReportTargetDTO,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import Model, QuerySet

    from ludamus.pacts.ids import SphereId
    from ludamus.pacts.report import ReportCreateData


_MODELS: dict[ReportedContentKind, type[Model]] = {
    ReportedContentKind.SESSION: Session,
    ReportedContentKind.USER: User,
}


def _public_sessions(sphere_id: SphereId) -> QuerySet[Session]:
    # What a visitor can open: sessions of this sphere's published or unlisted
    # events, the same rule the public event page applies.
    now = datetime.now(tz=UTC)
    return Session.objects.filter(event__sphere_id=sphere_id).filter(
        Q(event__publication_time__isnull=False, event__publication_time__lte=now)
        | Q(event__visibility=EventVisibility.UNLISTED)
    )


def _sphere_root(sphere_id: SphereId) -> str:
    domain = Sphere.objects.values_list("site__domain", flat=True).get(pk=sphere_id)
    return absolute_url("/", domain=domain)


def _session_target(object_id: int, sphere_id: SphereId) -> ReportTargetDTO | None:
    session = (
        _public_sessions(sphere_id)
        .select_related("event__sphere__site")
        .filter(pk=object_id)
        .first()
    )
    if session is None:
        return None
    path = reverse("web:chronology:event", kwargs={"slug": session.event.slug})
    return ReportTargetDTO(
        kind=ReportedContentKind.SESSION,
        object_id=session.pk,
        label=session.title,
        location=absolute_url(
            f"{path}?session={session.pk}", domain=session.event.sphere.site.domain
        ),
    )


def _user_target(object_id: int, sphere_id: SphereId) -> ReportTargetDTO | None:
    # A person's public face here is their name and avatar beside the sessions
    # they present, so only a presenter in this sphere can be reported from it.
    if not _public_sessions(sphere_id).filter(presenter_id=object_id).exists():
        return None
    user = User.objects.get(pk=object_id)
    return ReportTargetDTO(
        kind=ReportedContentKind.USER,
        object_id=user.pk,
        label=user.full_name,
        location=_sphere_root(sphere_id),
    )


_RESOLVERS: dict[
    ReportedContentKind, Callable[[int, SphereId], ReportTargetDTO | None]
] = {
    ReportedContentKind.SESSION: _session_target,
    ReportedContentKind.USER: _user_target,
}


def _kind_by_content_type() -> dict[int, ReportedContentKind]:
    content_types = ContentType.objects.get_for_models(*_MODELS.values())
    return {content_types[model].pk: kind for kind, model in _MODELS.items()}


def _dto(
    report: ContentReport, kinds: dict[int, ReportedContentKind]
) -> ContentReportDTO:
    return ContentReportDTO(
        pk=report.pk,
        kind=kinds[report.content_type_id],
        object_id=report.object_id,
        content_label=report.content_label,
        location=report.location,
        sphere_name=report.sphere.name if report.sphere else "",
        reason=ReportReason(report.reason),
        explanation=report.explanation,
        reporter_name=report.reporter_name,
        reporter_email=report.reporter_email,
        reporter_user_id=(
            None if report.reporter_id is None else UserId(report.reporter_id)
        ),
        status=ReportStatus(report.status),
        decision=report.decision,
        decided_by_name=report.decided_by.full_name if report.decided_by else "",
        decided_at=report.decided_at,
        decided_automatically=report.decided_automatically,
        creation_time=report.creation_time,
    )


def _reports() -> QuerySet[ContentReport]:
    return ContentReport.objects.select_related("sphere", "decided_by")


class ReportRepository(ReportRepositoryProtocol):
    @staticmethod
    def read_target(
        *, kind: ReportedContentKind, object_id: int, sphere_id: SphereId
    ) -> ReportTargetDTO | None:
        return _RESOLVERS[kind](object_id, sphere_id)

    @staticmethod
    def read_reporter(user_id: UserId) -> ReporterContactDTO:
        user = User.objects.get(pk=user_id)
        return ReporterContactDTO(name=user.name, email=user.email or "")

    @staticmethod
    def create(data: ReportCreateData) -> ContentReportDTO:
        report = ContentReport.objects.create(
            sphere_id=data.sphere_id,
            content_type=ContentType.objects.get_for_model(_MODELS[data.target.kind]),
            object_id=data.target.object_id,
            content_label=data.target.label,
            location=data.location,
            reason=data.reason,
            explanation=data.explanation,
            reporter_id=data.reporter_user_id,
            reporter_name=data.reporter_name,
            reporter_email=data.reporter_email,
            good_faith=True,
        )
        return _dto(_reports().get(pk=report.pk), _kind_by_content_type())

    @staticmethod
    def list_by_status(status: ReportStatus) -> list[ContentReportDTO]:
        kinds = _kind_by_content_type()
        return [
            _dto(report, kinds)
            for report in (
                _reports().filter(status=status).order_by("creation_time", "pk")
            )
        ]

    @staticmethod
    def read(report_id: int) -> ContentReportDTO | None:
        report = _reports().filter(pk=report_id).first()
        return None if report is None else _dto(report, _kind_by_content_type())

    @staticmethod
    def lock(report_id: int) -> ContentReportDTO | None:
        report = ContentReport.objects.select_for_update().filter(pk=report_id).first()
        return None if report is None else _dto(report, _kind_by_content_type())

    @staticmethod
    def mark_decided(
        *, report_id: int, decided_by_id: UserId, decision: str, now: datetime
    ) -> ContentReportDTO:
        ContentReport.objects.filter(pk=report_id).update(
            status=ReportStatus.DECIDED,
            decided_by_id=decided_by_id,
            decided_at=now,
            decision=decision,
            decided_automatically=False,
        )
        return _dto(_reports().get(pk=report_id), _kind_by_content_type())
