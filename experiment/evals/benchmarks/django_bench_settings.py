"""Django settings for the benchmark baseline: production serving, test data.

gunicorn needs WhiteNoise to serve the static files runserver --insecure
serves through finders; outside ENV=production the app sets no STATIC_ROOT,
so this module keeps the e2e settings and turns the finders on for WhiteNoise.
"""

from ludamus.edges.settings import *  # noqa: F403  # pylint: disable=wildcard-import,unused-wildcard-import

WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False
