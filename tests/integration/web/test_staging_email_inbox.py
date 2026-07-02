from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:staging-emails")

RAW_EMAIL = (
    'Content-Type: text/plain; charset="utf-8"\n'
    "Subject: A spot opened\n"
    "From: noreply@zagrajmy.net\n"
    "To: player@example.com\n"
    "Date: Wed, 01 Jul 2026 12:00:00 -0000\n"
    "\n"
    "Claim it before it goes to the next person.\n"
)


def _write_email(directory, *, name="20260701-000000-1.log", raw=RAW_EMAIL):
    file = directory / name
    file.write_bytes(raw.encode())
    return file


class TestStagingEmailInboxView:
    def test_404_when_not_file_backend(self, staff_client, settings):
        settings.EMAIL_FILE_PATH = None

        response = staff_client.get(URL)

        assert_response_404(response)

    def test_404_for_non_staff(self, authenticated_client, settings, tmp_path):
        settings.EMAIL_FILE_PATH = str(tmp_path)

        response = authenticated_client.get(URL)

        assert_response_404(response)

    def test_404_for_anonymous(self, client, settings, tmp_path):
        settings.EMAIL_FILE_PATH = str(tmp_path)

        response = client.get(URL)

        assert_response_404(response)

    def test_ok_empty(self, staff_client, settings, tmp_path):
        settings.EMAIL_FILE_PATH = str(tmp_path)

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"emails": []},
            template_name="staging_email_inbox.html",
        )

    def test_ok_shows_captured_email(self, staff_client, settings, tmp_path):
        settings.EMAIL_FILE_PATH = str(tmp_path)
        _write_email(tmp_path)

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "emails": [
                    {
                        "subject": "A spot opened",
                        "to": "player@example.com",
                        "date": "Wed, 01 Jul 2026 12:00:00 -0000",
                        "body": "Claim it before it goes to the next person.",
                    }
                ]
            },
            template_name="staging_email_inbox.html",
            contains=["A spot opened", "player@example.com"],
        )

    def test_multiple_messages_in_one_file_newest_first(
        self, staff_client, settings, tmp_path
    ):
        settings.EMAIL_FILE_PATH = str(tmp_path)

        def _msg(subject):
            return (
                'Content-Type: text/plain; charset="utf-8"\n'
                f"Subject: {subject}\n"
                "To: player@example.com\n"
                "\n"
                "body\n"
            )

        _write_email(tmp_path, raw=f"{_msg('Older')}{'-' * 79}\n{_msg('Newer')}")

        response = staff_client.get(URL)

        subjects = [email["subject"] for email in response.context_data["emails"]]
        assert subjects == ["Newer", "Older"], subjects

    def test_non_ascii_body_decoded(self, staff_client, settings, tmp_path):
        settings.EMAIL_FILE_PATH = str(tmp_path)
        _write_email(
            tmp_path,
            raw=(
                'Content-Type: text/plain; charset="utf-8"\n'
                "Content-Transfer-Encoding: 8bit\n"
                "MIME-Version: 1.0\n"
                "Subject: A spot opened =?utf-8?b?4oCU?= claim it\n"
                "To: =?utf-8?b?Z2/Fm8SH?=@example.com\n"
                "\n"
                "Zajmij miejsce — zanim przepadnie.\n"
            ),
        )

        response = staff_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "emails": [
                    {
                        "subject": "A spot opened — claim it",
                        "to": "gość@example.com",
                        "date": "",
                        "body": "Zajmij miejsce — zanim przepadnie.",
                    }
                ]
            },
            template_name="staging_email_inbox.html",
            contains=["Zajmij miejsce — zanim przepadnie.", "A spot opened — claim it"],
        )
