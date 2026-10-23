# RFC 0002 — Ticket sales on Stripe, and the yearly plan

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
- **The yearly plan ("White Glove")** — for conventions that run their programme
  on Zagrajmy but sell tickets elsewhere, so there is no per-ticket fee to
  collect. A sphere manager buys it self-serve (Stripe Checkout, subscription
  mode) and manages it in the Stripe billing portal; a maintainer can also
  record a plan paid by bank transfer in the admin.

The pricing page is out of scope here; the numbers it will quote live in one
place (`specs/tickets.py`, plus the yearly Stripe Price id in settings).

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
  grosz) and sent as `application_fee_amount`. That is the only number we
  control.
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
SpherePlan       1:1 Sphere   plan (standard | white_glove), source (stripe | manual),
                              paid_until, stripe_customer_id, stripe_subscription_id
PayoutAccount    1:1 Sphere   stripe_account_id, details_submitted,
                              charges_enabled, payouts_enabled
TicketType       N:1 Event    name, description, price (grosze), currency,
                              quantity (null = unlimited), sales_start/end,
                              is_archived, order
TicketOrder      N:1 Event    buyer, email, status, currency, total,
                              platform_fee, stripe_account_id,
                              stripe_checkout_session_id, stripe_payment_intent_id,
                              hold_until, paid_at, refunded_at
TicketOrderLine  N:1 Order    ticket_type, quantity, unit_price
Ticket           N:1 Order    ticket_type, holder, code (unique), is_void
StripeEvent                   stripe event id (unique), type, received_at
```

- Money is integer minor units everywhere. Currency is PLN in v1.
- A missing `SpherePlan` row reads as the standard plan; a missing
  `PayoutAccount` row as "not connected". No backfill migration.
- Ticket types are archived, never deleted, once anything was sold — orders
  point at them.
- `StripeEvent` makes webhook handling idempotent: Stripe retries, and an event
  id seen once is acknowledged and skipped.

## Flows

### Buying

1. The event page shows **Buy tickets** (primary) when at least one ticket type
   is on sale. The tickets page lists types with price and what is left.
2. The buyer picks quantities and submits. Signed-out buyers go through login
   first: a ticket belongs to an account, it is what "My tickets" lists.
3. The service locks the event's ticket types, checks availability and the
   sales window, and creates a `pending` order that **holds** its seats until
   `hold_until` (now + 30 min, Stripe's minimum Checkout lifetime). It then
   creates the Checkout Session with the same `expires_at`, so the hold and
   the session die together.
4. Stripe redirects back to the order page. It shows "paid" once the webhook
   landed and "confirming payment" until then (it refreshes itself).
5. Coming back through Stripe's "back" link expires the Checkout Session at once
   and releases the hold.

Availability = `quantity − sold − held`, where held counts `pending` orders whose
hold has not run out and `awaiting_payment` orders (delayed methods). An order
past its hold stops counting the moment the clock passes it: no sweep is needed
for correctness.

### Webhooks

Two endpoints, two signing secrets:

- `/hooks/stripe/connect` — events from organizers' accounts:
  `checkout.session.completed` (paid → issue tickets; unpaid → awaiting
  payment), `checkout.session.async_payment_succeeded` / `…_failed`,
  `checkout.session.expired`, `charge.refunded`, `account.updated`.
- `/hooks/stripe/billing` — Zagrajmy's own account (the yearly plan):
  `checkout.session.completed` (subscription mode), `invoice.paid`,
  `customer.subscription.updated` / `.deleted`.

Every handler is idempotent on its own as well (a paid order is not paid twice),
the `StripeEvent` log is the first line, not the only one.

### Refunds

The organizer refunds a whole order from the event panel. That calls Stripe
with `refund_application_fee=True`: a refunded ticket was not sold, so we do not
keep 3.5% of it. Stripe keeps its own fee. A refund made in the Stripe dashboard
arrives as `charge.refunded` and voids the tickets the same way.

## States

`TicketOrder.status`: `pending` → `paid` | `expired` | `awaiting_payment`;
`awaiting_payment` → `paid` | `failed`; `paid` → `refunded`.

## Failure modes, and what each does

| What goes wrong                             | What happens                                                      |
| ------------------------------------------- | ----------------------------------------------------------------- |
| Two buyers race for the last ticket         | Ticket types are row-locked; the second gets "sold out".          |
| Buyer abandons Checkout                     | Hold lapses at `hold_until`; `checkout.session.expired` marks it. |
| Webhook arrives twice                       | `StripeEvent` unique id; second delivery is a 200 no-op.          |
| Webhook never arrives                       | Order page shows "confirming"; Stripe retries for 3 days.         |
| Stripe API down when creating Checkout      | Order is cancelled, hold released, buyer sees a retry message.    |
| Organizer's account loses `charges_enabled` | Tickets page stops selling, panel says why and links onboarding.  |
| Forged webhook                              | Signature check fails → 400, logged, nothing changes.             |
| Order id from another sphere/event          | Every read is scoped to the buyer or the panel's event → 404.     |

## Out of scope (v1)

- The pricing page.
- Passing fees to the buyer; discount codes; tax/VAT invoices for tickets
  (Stripe receipts only — the organizer is the seller of record).
- Check-in scanning (codes and QR are issued and shown, nothing scans them yet).
- Gating session enrollment on holding a ticket. The hook exists: enrollment
  already asks `TicketAPIProtocol.fetch_membership_count`, which a native
  "paid tickets for this email" counter can answer.
- Partial refunds and per-ticket transfers.

## Open questions

1. Should the yearly plan waive the 3.5% if a White Glove sphere also sells on
   Zagrajmy? v1 charges it on all tickets, per the brief; the rate is a
   per-plan lookup in `specs/tickets.py`, so waiving is one line.
2. Refunds return our fee (`refund_application_fee=True`). Keep it?
3. Do we require login to buy, or add guest checkout by email later?
