"""Django settings for the benchmark baseline: the e2e settings served by gunicorn.

Outside ENV=production the app sets no STATIC_ROOT, so WhiteNoise serves the
static files through the finders, the same files runserver --insecure serves.
"""

from ludamus.edges import settings as base_settings

globals().update(
    {name: getattr(base_settings, name) for name in dir(base_settings) if name.isupper()}
)

WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False
