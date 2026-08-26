import pytest

from ludamus.links.analytics import identity


class TestEnvironment:
    @pytest.mark.parametrize(
        ("env", "is_staging", "expected"),
        (
            ("production", False, "production"),
            # Staging runs ENV=production so it stays production-shaped, which
            # leaves IS_STAGING as the only thing separating the two.
            ("production", True, "staging"),
            ("development", False, "development"),
        ),
    )
    def test_reports_the_deployment(self, settings, env, is_staging, expected):
        settings.ENV = env
        settings.IS_STAGING = is_staging

        assert identity.environment() == expected


class TestDistinctId:
    def test_production_keeps_the_bare_pk(self, settings):
        # Production persons already exist under bare pks; prefixing them now
        # would fork every timeline at the deploy that did it.
        settings.ENV = "production"
        settings.IS_STAGING = False

        assert identity.distinct_id(42) == "42"

    def test_other_deployments_are_namespaced(self, settings):
        settings.ENV = "production"
        settings.IS_STAGING = True

        assert identity.distinct_id(42) == "staging:42"

    def test_staging_and_production_cannot_collide(self, settings):
        # The whole point: one project, two databases, independent sequences.
        settings.ENV = "production"
        settings.IS_STAGING = True
        staging = identity.distinct_id(42)
        settings.IS_STAGING = False

        assert staging != identity.distinct_id(42)
