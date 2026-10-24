from ludamus.gates.web.django.checks import (
    POSTAL_ADDRESS_MISSING,
    check_mail_postal_address,
)


class TestMailPostalAddressCheck:
    def test_production_without_an_address_warns(self, settings):
        settings.IS_PRODUCTION = True
        settings.MAIL_POSTAL_ADDRESS = ""

        assert [m.id for m in check_mail_postal_address()] == [POSTAL_ADDRESS_MISSING]

    def test_production_with_an_address_passes(self, settings):
        settings.IS_PRODUCTION = True
        settings.MAIL_POSTAL_ADDRESS = "ul. Przykładowa 1, 00-001 Warszawa"

        assert not check_mail_postal_address()

    def test_development_never_warns(self, settings):
        settings.IS_PRODUCTION = False
        settings.MAIL_POSTAL_ADDRESS = ""

        assert not check_mail_postal_address()
