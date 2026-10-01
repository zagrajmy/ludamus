from ludamus.links.analytics import identity


def test_staging_reports_itself_despite_running_as_production(settings):
    # Staging runs ENV=production so it stays production-shaped, which leaves
    # IS_STAGING as the only thing separating the two.
    settings.ENV = "production"
    settings.IS_STAGING = True

    assert identity.environment() == "staging"


class TestDistinctId:
    def test_production_keeps_the_bare_pk(self, settings):
        # Production persons already exist under bare pks; prefixing them now
        # would fork every timeline at the deploy that did it.
        settings.ENV = "production"
        settings.IS_STAGING = False

        assert identity.distinct_id(42) == "42"

    def test_other_deployments_are_namespaced(self, settings):
        # One project, two databases, independent sequences.
        settings.ENV = "production"
        settings.IS_STAGING = True

        assert identity.distinct_id(42) == "staging:42"
