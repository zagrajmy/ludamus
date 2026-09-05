"""Crowd business invariants."""

from datetime import timedelta

# Minimum gap between two verification mails to the same account; one clock
# (`email_verification_sent_at`) serves the resend button and the bulk
# reminder sweep alike.
EMAIL_VERIFICATION_RESEND_THROTTLE = timedelta(minutes=5)

# How long an unverified account is left alone before the sweep re-nags it.
EMAIL_VERIFICATION_REMINDER_INTERVAL = timedelta(days=7)
