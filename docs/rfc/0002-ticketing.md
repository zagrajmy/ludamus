# RFC 0002 — Ticket sales on Stripe, and the Technical Partner deal

**Status:** 🟡 v1 built (this branch). Open questions at the end.
**Touches:** sphere panel (plan, payouts), event panel (tickets, orders), the
public event page, the profile (my tickets), two Stripe webhooks.

## TL;DR

An event either sells tickets on Zagrajmy or it doesn't. Most don't: a meetup is
free, and a big convention may already sell entry through its own shop (Sklep
Kapitularz is wired in as a _ticketing integration_). So:

- **Free events change nothing.** No ticket types → no ticket UI anywhere.
- **Selling on Zagrajmy** — the organizer connects their own Stripe account,
  adds ticket types, and buyers pay through Stripe Checkout. The money lands in
  the organizer's Stripe balance. Zagrajmy takes **3.5% of every ticket** as a
  Stripe _application fee_; Stripe takes its processing fee (2.9% + 0.30 on the
  headline card rate) from the organizer's side of the same charge.
- **Buying needs no account.** A guest pays in Checkout and lands on an order
  page at a secret link, which we also email them. Signing in there (new
  account or old) claims the order and its tickets into that account.
- **Deals, and the Technical Partner tier.** We sell outcomes, not software, so
  the money is kept apart from the help:
  - _Terms_: a sphere's ticket fee (3.5% unless a deal lowers it, down to 0)
    and, if agreed, a fixed yearly price.
  - _Technical Partner_: the Zagrajmy team runs the technical side of the
    convention with the organizers — setup, the programme, help on the day.
  Both are agreed per convention and recorded by a maintainer; nothing is
  bought by clicking. A fixed price is billed by a Stripe subscription made in
  the dashboard, or by bank transfer.

The pricing page is out of scope here; the standard rate it will quote lives in
one place (`STANDARD_TICKET_FEE_BPS` in `pacts/billing.py`).

## Who pays what

For a 50,00 zł ticket:

| Line                     | Amount   | Where it goes            |
| ------------------------ | -------- | ------------------------ |
| Buyer pays               | 50,00 zł | organizer's Stripe acct. |
| Zagrajmy fee (3.5%)      | −1,75 zł | Zagrajmy's Stripe acct.  |
| Stripe fee (2.9% + 0,30) | −1,75 zł | Stripe                   |
| Organizer keeps          | 46,50 zł |                          |

- Fees are per **order** (one Stripe charge), not per ticket, so buying three
  tickets at once costs the organizer one fixed 0,30, not three.
- The Zagrajmy fee is computed by us (`platform_fee()`, round half up to the
  grosz) at the sphere's rate (`specs.billing.current_terms`) and sent as
  `application_fee_amount`. That is the only number we control. A deal's rate
  applies while the deal holds; it can only be lower than the standard one.
- The Stripe fee is Stripe's. We show an _estimate_ in the panel ("you keep
  about …"); the real fee varies with card country and payment method (BLIK,
  Przelewy24) and appears in the organizer's Stripe dashboard.
- The buyer sees one price. Passing fees on to the buyer is a later option.

## Stripe architecture

**Connect, direct charges, organizer-owned accounts.** Each sphere that sells
tickets gets one connected account, created with controller properties that
make it a full Stripe account the organizer owns:

```python
controller = {
    "fees": {"payer": "account"},        # Stripe's fee comes off their balance
    "losses": {"payments": "stripe"},     # disputes are not Zagrajmy's liability
    "stripe_dashboard": {"type": "full"}, # they see payouts, refunds, disputes
}
```

Checkout Sessions are created **on the connected account** (`stripe_account=`)
with `payment_intent_data.application_fee_amount`. This is what makes the
pricing literal: Stripe debits its fee from the organizer, and our 3.5% is a
separate transfer to us. The alternative, destination charges on Express
accounts, makes Zagrajmy pay Stripe's fee and forces us to guess it inside the
application fee — it would drift every time Stripe's rate does.

Onboarding is Stripe-hosted (Account Links). We keep only the account id and
three flags Stripe reports (`details_submitted`, `charges_enabled`,
`payouts_enabled`), refreshed on return from onboarding and on every
`account.updated` webhook.

Checkout is Stripe-hosted too: cards, BLIK and Przelewy24 come from the
account's payment method settings, and we never touch card data (PCI SAQ A).

## Data model

```text
SpherePlan       1:1 Sphere   technical_partner, ticket_fee_bps (null = standard,
                              ≤ 350), yearly_price (grosze), source (stripe | manual),
                              paid_until, stripe_customer_id, stripe_subscription_id
PayoutAccount    1:1 Sphere   stripe_account_id, details_submitted,
                              charges_enabled, payouts_enabled
TicketType       N:1 Event    name, description, price (grosze), currency,
                              quantity (null = unlimited), sales_start/end,
                              is_archived, order
TicketOrder      N:1 Event    reference (secret, unique), buyer (null = guest),
                              email, status, currency, total,
                              platform_fee, stripe_account_id,
                              stripe_checkout_session_id, stripe_payment_intent_id,
                              hold_until, paid_at, refunded_at
TicketOrderLine  N:1 Order    ticket_type, quantity, unit_price
Ticket           N:1 Order    ticket_type, holder, code (unique)
```

- Money is integer minor units everywhere. Currency is PLN in v1.
- A missing `SpherePlan` row, one past its `paid_until`, or one with no terms
  on it reads as no deal: the standard fee, no Technical Partner. A missing
  `PayoutAccount` row reads as "not connected". No backfill migration.
- Ticket types are archived, never deleted, once anything was sold — orders
  point at them.
- Orders move only along `specs.tickets.ORDER_TRANSITIONS`, and every write is
  guarded by the status it moves from (`UPDATE … WHERE status IN …`). That is
  what makes webhooks idempotent: a redelivered or reordered event finds the
  order already past it, changes nothing and is acknowledged as `stale`.

## Flows

### Buying

1. The event page shows **Buy tickets** (primary) when at least one ticket type
   is on sale. The tickets page lists types with price and what is left.
2. The buyer picks quantities and submits, signed in or not. A signed-in buyer's
   email goes to Checkout; a guest types it there. One guest network (an IPv4
   address, or an IPv6 /64, stored only as an HMAC) may hold three unpaid
   orders per event at once; the count runs under the event's lock, so
   parallel requests cannot slip past it. A bank transfer can hold seats for
   days, so this is what stops a script sitting on a sell-out.
3. The service locks the event's ticket types, checks availability and the
   sales window, and creates a `pending` order that **holds** its seats until
   `hold_until` (now + 31 min, just over Stripe's minimum Checkout lifetime).
   It then creates the Checkout Session with the same `expires_at`, so the hold
   and the session die together.
   The buy view runs outside the request transaction, so the hold commits,
   and the event's lock is released, before the Stripe call.
4. Stripe redirects back to the order page, at `/tickets/orders/<reference>/`.
   It shows "paid" once the webhook landed and "confirming payment" until then
   (it refreshes itself). The webhook that completes Checkout stores the email
   the buyer typed and mails them the page's link, once.
5. A guest's order page offers **Create an account** and **Log in** (Auth0, back
   to the same page). Signed in, **Add to my account** claims the order: it and
   its tickets move to that account — a new one or an existing one, so this is
   also how a guest merges a purchase into the account they already had.
   The link alone is not enough: buyers forward the order mail to friends. An
   account verified for the order's email claims at once; any other account
   gets a confirmation link mailed to the order's email (signed, bound to the
   order and the account, valid a day). From then on only that account sees
   the order; anyone else with the link is asked to sign in.
6. Coming back through Stripe's "back" link expires the Checkout Session at once
   and releases the hold.

Availability = `quantity − sold − held`, where held counts `awaiting_payment`
orders (delayed methods) and `pending` orders until an hour past their hold
(`WEBHOOK_GRACE`). A buyer may pay in the last minute of the hold and Stripe may
report it late; the grace keeps those seats from being sold to someone else
meanwhile. Stripe's `checkout.session.expired` releases an abandoned hold at
once, so the grace only matters when webhooks are delayed. No sweep is needed
for correctness.

### Webhooks

Two endpoints, two signing secrets:

- `/hooks/stripe/connect` — events from organizers' accounts:
  `checkout.session.completed` (paid → issue tickets; unpaid → awaiting
  payment), `checkout.session.async_payment_succeeded` / `…_failed`,
  `checkout.session.expired`, `charge.refunded`, `account.updated`.
- `/hooks/stripe/billing` — Zagrajmy's own account (a deal's fixed price):
  `customer.subscription.created` / `.updated` / `.deleted`.

Stripe does not deliver in order. Ticket orders are protected by the transition
guards above. A subscription event only names a subscription and its customer:
the plan's row is locked, then the subscription's state (live or ended, paid
until when) is read back from Stripe and written as the deal's `paid_until`,
so the last delivery writes the latest state whatever order they came in. An
ended subscription other than the one on record changes nothing, and a deal
paid by transfer (`source=manual`) is never touched. If Stripe cannot be
reached the endpoint answers 503 and Stripe retries.

### Refunds

The organizer refunds a whole order from the event panel. That calls Stripe
with `refund_application_fee=True`: a refunded ticket was not sold, so we do not
keep 3.5% of it. Stripe keeps its own fee. A refund made in the Stripe dashboard
arrives as `charge.refunded` and voids the tickets the same way.

## States

`TicketOrder.status`: `pending` → `paid` | `expired` | `awaiting_payment` |
`failed`; `awaiting_payment` → `paid` | `failed`; `paid` → `refunded`. The table
lives in `specs.tickets.ORDER_TRANSITIONS`, and every move derives the statuses
it may leave from it.

## Failure modes, and what each does

| What goes wrong                             | What happens                                                      |
| ------------------------------------------- | ----------------------------------------------------------------- |
| Two buyers race for the last ticket         | Ticket types are row-locked; the second gets "sold out".          |
| Buyer abandons Checkout                     | Hold lapses at `hold_until`; `checkout.session.expired` marks it. |
| Webhook arrives twice or out of order       | Transition guard; the late delivery is a 200 `stale` no-op.       |
| Paid webhook arrives after the hold         | Seats stay held for `WEBHOOK_GRACE`; an oversell is logged.       |
| Payment lands for an order we gave up on    | Refunded at once (retried by Stripe if refused); nothing issued.  |
| Webhook never arrives                       | Order page shows "confirming"; Stripe retries for 3 days.         |
| Stripe API down when creating Checkout      | Order is cancelled, hold released, buyer sees a retry message.    |
| Organizer's account loses `charges_enabled` | Tickets page stops selling, panel says why and links onboarding.  |
| Forged webhook                              | Signature check fails → 400, logged, nothing changes.             |
| Order id from another sphere/event          | Scoped to the panel's event, or the link's event → 404.           |
| Guest order link forwarded or leaked        | Seen by its holders; claimed only via the order's email.          |
| A script starts guest checkouts in bulk     | Three unpaid orders per network per event, counted under lock.    |

## Out of scope (v1)

- The pricing page.
- Passing fees to the buyer; discount codes; tax/VAT invoices for tickets
  (Stripe receipts only — the organizer is the seller of record).
- Check-in scanning (codes and QR are issued and shown, nothing scans them yet).
- Gating session enrollment on holding a ticket. The hook exists: enrollment
  already asks `TicketAPIProtocol.fetch_membership_count`, which a native
  "paid tickets for this email" counter can answer.
- Partial refunds and per-ticket transfers.

## Decided

1. The ticket fee is part of each deal: a Technical Partner may pay less than
   3.5%, or nothing, as agreed (`SpherePlan.ticket_fee_bps`).
2. Refunds return our fee (`refund_application_fee=True`).
3. Guests buy without an account and claim the order into one afterwards.
