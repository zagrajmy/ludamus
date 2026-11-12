from ludamus.pacts.moderation import NoticeCategory

# Reports of child sexual abuse material may be anonymous (DSA Art. 16(2)(c)).
ANONYMOUS_NOTICE_CATEGORIES = frozenset({NoticeCategory.CHILD_SEXUAL_ABUSE})
# Staff read these first, and may owe the police or Dyżurnet.pl a report.
URGENT_NOTICE_CATEGORIES = frozenset(
    {NoticeCategory.CHILD_SEXUAL_ABUSE, NoticeCategory.CHILD_SAFETY}
)
NOTICES_PER_ADDRESS = 5
NOTICE_WINDOW_SECONDS = 60 * 60
# Art. 24(2): the average runs over the last six months.
ACTIVE_RECIPIENT_MONTHS = 6
