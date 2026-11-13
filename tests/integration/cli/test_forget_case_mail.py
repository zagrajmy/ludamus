from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from ludamus.links.db.django.models import CaseEmail, ModerationCase

_THREE_YEARS = timedelta(days=3 * 365)


def _mail(case, address, *, age):
    email = CaseEmail.objects.create(
        case=case, direction="in", message_id=f"<{address}>", address=address
    )
    CaseEmail.objects.filter(pk=email.pk).update(created_at=timezone.now() - age)


def test_forgets_case_mail_three_years_on_and_keeps_the_case():
    case = ModerationCase.objects.create(title="Pytanie")
    _mail(case, "old@example.com", age=_THREE_YEARS + timedelta(hours=1))
    _mail(case, "young@example.com", age=_THREE_YEARS - timedelta(hours=1))
    out = StringIO()

    call_command("forget_case_mail", stdout=out)

    assert "Forgot 1 case email(s) past their retention." in out.getvalue()
    assert list(CaseEmail.objects.values_list("address", flat=True)) == [
        "young@example.com"
    ]
    assert ModerationCase.objects.filter(pk=case.pk).exists()
