# NOTE: migration 0147_sphere_membership_role names
# `ludamus.pacts.multiverse.SphereRole`. Migrations are never edited, so that
# dotted path keeps resolving here. Everything else imports ludamus.pacts.sphere.
from ludamus.pacts.sphere import SphereRole

__all__ = ["SphereRole"]
