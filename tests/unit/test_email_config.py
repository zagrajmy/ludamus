import pytest
from django.core.exceptions import ImproperlyConfigured

from ludamus.edges.email import email_config

RESEND = "smtp://resend:re_key@smtp.resend.com:587"
RESEND_PORT = 587


class TestTransport:
    def test_smtp_url_keeps_host_port_and_credentials(self):
        config = email_config(RESEND)

        assert config["EMAIL_BACKEND"] == "django.core.mail.backends.smtp.EmailBackend"
        assert config["EMAIL_HOST"] == "smtp.resend.com"
        assert config["EMAIL_PORT"] == RESEND_PORT
        assert config["EMAIL_HOST_USER"] == "resend"
        assert config["EMAIL_HOST_PASSWORD"] == "re_key"

    def test_console_url_needs_no_flags(self):
        config = email_config("consolemail://")

        assert (
            config["EMAIL_BACKEND"] == "django.core.mail.backends.console.EmailBackend"
        )
        assert "EMAIL_USE_TLS" not in config

    def test_file_url_keeps_its_path(self):
        config = email_config("filemail:///app/logs/emails")

        assert config["EMAIL_FILE_PATH"] == "app/logs/emails"


class TestFlags:
    @pytest.mark.parametrize("value", ("True", "true", "1", "yes", "on"))
    def test_tls_parameter_turns_tls_on(self, value):
        assert email_config(f"{RESEND}/?tls={value}")["EMAIL_USE_TLS"] is True

    @pytest.mark.parametrize("value", ("False", "false", "0", "no", "off"))
    def test_tls_parameter_turns_tls_off(self, value):
        assert email_config(f"{RESEND}/?tls={value}")["EMAIL_USE_TLS"] is False

    def test_ssl_parameter_turns_ssl_on(self):
        assert email_config(f"{RESEND}/?ssl=true")["EMAIL_USE_SSL"] is True

    def test_scheme_still_turns_tls_on(self):
        config = email_config("smtp+tls://resend:re_key@smtp.resend.com:587")

        assert config["EMAIL_USE_TLS"] is True

    def test_parameter_overrides_the_scheme(self):
        config = email_config("smtp+tls://resend:re_key@smtp.resend.com:587/?tls=off")

        assert config["EMAIL_USE_TLS"] is False


class TestRejections:
    def test_unreadable_parameter_is_refused(self):
        with pytest.raises(ImproperlyConfigured, match="does not read"):
            email_config(f"{RESEND}/?starttls=True")

    def test_flag_that_is_not_a_boolean_is_refused(self):
        with pytest.raises(ImproperlyConfigured, match="expects a boolean"):
            email_config(f"{RESEND}/?tls=maybe")
