import re

# "[Z-1234]" anywhere in a subject, as replies and forwards keep it.
STAFF_CASE_SUBJECT_REFERENCE = re.compile(r"\[Z-(\d{1,9})\]", re.IGNORECASE)
