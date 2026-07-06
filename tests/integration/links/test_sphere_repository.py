from ludamus.links.db.django.repositories import SphereRepository


class TestSphereRepositoryDomainExists:
    def test_returns_true_for_matching_domain(self, sphere):
        assert SphereRepository.domain_exists(sphere.site.domain) is True

    def test_returns_false_for_unknown_domain(self):
        assert SphereRepository.domain_exists("no-such-domain.example") is False
