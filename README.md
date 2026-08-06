# Kavyn Backend — Stripe Checkout Fix

## What was wrong

Checkout was failing with:

```
Received unknown parameter: automatic_payment_methods
```

`automatic_payment_methods` is a valid parameter for Stripe's **PaymentIntents**
API, but it isn't accepted by **Checkout Sessions** (`stripe.checkout.Session.create`).
Stripe rejected the request outright, so no session was ever created.

## What changed

In `server.py`, inside `create_checkout_session()`, the line

```python
automatic_payment_methods={"enabled": True},
```

was removed. You don't need it — Checkout Sessions automatically offer
whichever payment methods you've turned on in your Stripe Dashboard
(**Settings → Payment methods**: cards, Apple Pay, Google Pay, Link, etc.)
without any extra parameter. That's the entire fix; nothing else in the
checkout flow changed.

## Shipping address & phone — already handled

You mentioned not wanting to ask customers for their info twice. Good news:
this backend was already set up correctly for that. These two lines in the
same function tell Stripe to collect shipping address and phone **on Stripe's
own checkout page**:

```python
shipping_address_collection={"allowed_countries": ["CA"]},
phone_number_collection={"enabled": True},
```

So the flow is: your site asks for **email only** → Stripe's secure page
collects shipping address, phone, and payment details in one step → your
site shows the confirmation. Nothing is asked twice. (The matching frontend
change — trimming the checkout form down to just the email field — is in the
site update, not this backend.)

## Redeploying

Upload `server.py` to wherever your backend lives (Render, or wherever you
move it — see the hosting notes below) and redeploy/restart the service. No
environment variables, dependencies, or database changes are needed.

## Free hosting alternative to Render

Render's free tier works but sleeps after 15 minutes of inactivity, so the
first visitor after a quiet period waits 5–15+ seconds. If you want to avoid
that:

**Google Cloud Run** is the strongest free option for a FastAPI app like this
one — it has a genuinely permanent free tier (not a trial), it's built for
exactly this kind of containerized app (you already have a `Dockerfile`), and
its cold starts are typically 1–3 seconds rather than Render's 30–60. The
trade-off is it's a bit more setup than Render's one-click GitHub deploy —
you'll use the `gcloud` CLI or the Cloud Run console to deploy the container.

Other options worth knowing about: **Fly.io** and **Koyeb** both offer
scale-to-zero free tiers similar in spirit to Render's.

## Can this run on your existing Hostinger plan?

If your current Hostinger plan is shared/business hosting (the kind that runs
your WordPress/WooCommerce store), **no** — shared hosting only supports
WSGI-based Python apps (via Passenger), and FastAPI is an ASGI framework that
needs Uvicorn to run correctly. It won't run reliably there.

To host this backend on Hostinger, you'd need to upgrade to a **Hostinger
VPS** plan (their KVM plans start around $4.99/mo). A VPS gives you root
access, so you can install Python, run Uvicorn/Gunicorn yourself behind
Nginx, and keep everything — store, backend, and domain — with one provider.
It's not free, but it's an option if you'd rather consolidate hosting than
run a separate free service.
