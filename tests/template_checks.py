"""Template variable error detection for tests.

Django silently swallows AttributeError when resolving template variables,
making it hard to detect missing methods/properties on model objects.

This module provides a logging filter that raises exceptions when Django
logs a template variable resolution failure.

See: https://code.djangoproject.com/ticket/11909
See: https://adamj.eu/tech/2022/03/30/how-to-make-django-error-for-undefined-template-variables/
"""

import inspect
import logging

from django.template.base import FilterExpression

MIN_ARGS = 2


class MissingTemplateVariableError(Exception):
    """Raised when a template variable cannot be resolved."""

    def __init__(self, variable_name: str, template_name: str, context: str) -> None:
        super().__init__(f"{variable_name!r} missing in {template_name!r}{context}")


class MissingTemplateVariableFilter(logging.Filter):
    """Logging filter that raises on template variable resolution failures.

    Django logs all variable resolution failures at DEBUG level with the message
    "Exception while resolving variable ...". This filter intercepts those logs
    and raises an exception instead of silently continuing.

    Excludes third-party templates (admin, debug_toolbar) that may rely on
    missing variable defaults.
    """

    ignored_template_prefixes = ("admin/", "debug_toolbar/", "django/")

    # Lookups that are expected to fail (variable_name, object_type)
    # e.g., session keys that may not exist
    ignored_lookups: tuple[tuple[str, str], ...] = (("theme", "SessionStore"),)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg.startswith("Exception while resolving variable "):
            variable_name, template_name = record.args  # type: ignore[misc]
            if variable_name.startswith("anonymous_enrollment_"):
                return False

            if template_name.startswith(self.ignored_template_prefixes):
                return False

            # Check if this lookup should be ignored
            lookup_info = self._get_lookup_info(record)
            if lookup_info and lookup_info in self.ignored_lookups:
                return False

            if self._has_default_filter_on_simple_var():
                return True

            # Extract additional context from the exception
            context = self._extract_exception_context(record)
            raise MissingTemplateVariableError(
                variable_name=variable_name,
                template_name=template_name,
                context=context,
            ) from None
        return False

    def _has_default_filter_on_simple_var(self) -> bool:
        # Walk f_back rather than inspect.stack(): stack() resolves source
        # context (linecache read + module lookup) for every frame, and we
        # only need each frame's locals. It fires on every failed template
        # variable lookup, so the waste dominates the test suite.
        frame = inspect.currentframe()
        while frame is not None:  # pylint: disable=while-used
            local_self = frame.f_locals.get("self")
            if isinstance(local_self, FilterExpression):
                var = local_self.var
                if hasattr(var, "lookups") and var.lookups and len(var.lookups) == 1:
                    for func, _args in local_self.filters:
                        if func.__name__ == "default":
                            return True
                break
            frame = frame.f_back
        return False

    def _get_lookup_info(self, record: logging.LogRecord) -> tuple[str, str] | None:
        if not record.exc_info:
            return None

        _, exc_value, _ = record.exc_info
        if exc_value is None:
            return None

        if hasattr(exc_value, "args") and exc_value.args:
            args = exc_value.args
            if (
                len(args) >= MIN_ARGS
                and isinstance(args[1], tuple)
                and len(args[1]) >= MIN_ARGS
            ):
                key, obj = args[1][:2]
                return (str(key), type(obj).__name__)

        return None

    def _extract_exception_context(self, record: logging.LogRecord) -> str:
        if not record.exc_info:
            return ""

        __, exc_value, ___ = record.exc_info
        if exc_value is None:
            return ""

        # VariableDoesNotExist stores args as (message_template, (key, object))
        # e.g., ("Failed lookup for key [%s] in %r", ("theme", <Session>))
        if hasattr(exc_value, "args") and exc_value.args:
            args = exc_value.args
            if (
                len(args) >= MIN_ARGS
                and isinstance(args[1], tuple)
                and len(args[1]) >= MIN_ARGS
            ):
                key, obj = args[1][:2]
                obj_type = type(obj).__name__
                return f" (lookup '{key}' failed on {obj_type})"

        # Fallback: use the exception message directly
        if exc_msg := str(exc_value):
            return f" ({exc_msg})"

        return ""
