from ludamus.pacts.moderation import NoticeCategory

# DSA Art. 16(2)(c): no name or email is asked for offences under Arts 3-7 of
# Directive 2011/93/EU, the sexual abuse and the grooming of children.
ANONYMOUS_NOTICE_CATEGORIES = frozenset(
    {NoticeCategory.CHILD_SEXUAL_ABUSE, NoticeCategory.CHILD_SAFETY}
)
# Staff read these first, and may owe the police or Dyżurnet.pl a report.
URGENT_NOTICE_CATEGORIES = frozenset(
    {NoticeCategory.CHILD_SEXUAL_ABUSE, NoticeCategory.CHILD_SAFETY}
)
NOTICES_PER_ADDRESS = 5
NOTICE_WINDOW_SECONDS = 60 * 60
# The receipt goes to whatever address the form was given, so any one address
# gets a few a day at most, however many notices name it.
RECEIPTS_PER_ADDRESS = 3
RECEIPT_WINDOW_SECONDS = 24 * 60 * 60
# Art. 24(2): the average runs over the last six months.
ACTIVE_RECIPIENT_MONTHS = 6
