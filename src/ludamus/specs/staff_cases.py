import re
from datetime import timedelta

# "[Z-1234]" anywhere in a subject, as replies and forwards keep it.
STAFF_CASE_SUBJECT_REFERENCE = re.compile(r"\[Z-(\d{1,9})\]", re.IGNORECASE)
# A case's mail and thread are kept this long (privacy policy, point 6).
STAFF_CASE_RETENTION = timedelta(days=3 * 365)
