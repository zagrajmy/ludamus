import re
from datetime import timedelta

# NOTE: posts carry it; the Worker keeps a case thread this long, not a year.
STAFF_CASE_RETENTION = timedelta(days=3 * 365)
STAFF_CASE_SUBJECT_REFERENCE = re.compile(r"\[Z-(\d{1,9})\]", re.IGNORECASE)
STAFF_THREAD_POST_TTL = timedelta(minutes=10)
STAFF_EMAIL_SUBJECT_FALLBACK = "(bez tematu)"
