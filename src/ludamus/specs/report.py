"""Business invariants for reports of illegal content."""

# Reports one reporter may send per window: a signed-in reporter is counted by
# account, a signed-out one by IP address. Generous for a person reporting
# what they saw, tight enough that the form cannot flood the queue or send a
# stream of receipts to someone else's inbox.
REPORTS_PER_WINDOW = 5
REPORT_WINDOW_SECONDS = 60 * 60
