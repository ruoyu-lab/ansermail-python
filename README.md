# ansermail (Python)

The SDK for [Anser](https://mail.ruoyulab.dev): send and receive email through its HTTP API. Python 3.10+, typed
(`TypedDict`s, checked with mypy `--strict`), no dependencies.

## Install

```bash
pip install git+https://github.com/ruoyu-lab/ansermail-python
```

It is not on PyPI yet, so pip installs it from GitHub; add a tag such as `@v0.1.0` to pin a release.

## Sending

```python
import datetime
from ansermail import Anser

anser = Anser("ms_…")  # or Anser() with ANSER_API_KEY set

sent = anser.emails.send(
    {
        "from": "Acme <hello@acme.com>",
        "to": {"email": "amy@example.com", "name": "Amy"},  # or "Amy <amy@example.com>", or a list
        "subject": "Welcome",
        "html": "<p>Hi Amy</p>",
        "attachments": [{"filename": "invoice.pdf", "content": pdf_bytes}],  # bytes, or base64 text
        "tags": {"category": "welcome"},
        # optional, up to 30 days; a datetime needs a time zone
        "scheduled_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
)
sent["id"]  # and its status, recipients, tags…

email = anser.emails.get(sent["id"])  # with the body, attachments and delivery details
anser.emails.update(sent["id"], scheduled_at="2026-12-01T09:00:00Z")
anser.emails.cancel(sent["id"])

# up to 100; all or none, unless atomic=False
batch = anser.emails.send_batch(
    [
        {"from": "hello@acme.com", "to": "amy@example.com", "subject": "Hi", "text": "Hi Amy"},
        {"from": "hello@acme.com", "to": "bob@example.com", "subject": "Hi", "text": "Hi Bob"},
    ],
    atomic=False,
)
batch["data"]  # one per email, None for a refused one
batch["errors"]  # [{"index", "code", "message", "param"}]
```

Every send, batch, reply and forward carries an idempotency key, so a retry never sends twice. Pass your own to make a
repeated call (a job that runs again) safe too: `anser.emails.send(params, idempotency_key=f"welcome-{user.id}")`.

## Templates

Templates are Handlebars (`{{name}}`, `{{#if}}`, `{{#each}}`, helpers like `formatDate`). Edits change the draft; publishing
saves it as the next version, and emails always use the latest published version. A variable the template prints but the
call does not give refuses the email (`template_variable_missing`).

```python
anser.templates.create(
    {
        "name": "Welcome",
        "alias": "welcome",  # send and look it up by this instead of the id
        "subject": "Welcome, {{name}}",
        "html": "<p>Hi {{name}}</p>{{#if coupon}}<p>Your code: {{coupon}}</p>{{/if}}",
        "from": "Acme <hello@acme.com>",  # used when the email gives none
    }
)
anser.templates.publish("welcome")  # version 1

anser.emails.send(
    {"to": "amy@example.com", "template": {"id": "welcome", "variables": {"name": "Amy", "coupon": "HELLO10"}}}
)  # from, subject and reply_to given here win over the template's

# try a change out without storing it; every field's problems come back together
result = anser.templates.render({"html": "<p>{{name}}</p>", "variables": {"name": "Amy"}})

anser.templates.update("welcome", {"subject": "Hello, {{name}}"})  # the draft only
anser.templates.versions("welcome")  # [{"version", "subject", "published_at", "published_by"}]
anser.templates.restore("welcome", 1)  # back into the draft; publish to send it again
```

## Lists

```python
page = anser.emails.list(limit=50, status="bounced")  # page.data, page.has_more

for email in anser.emails.list_all(status="bounced"):
    print(email["to"])
```

## The inbox

```python
address = anser.inbox.address()  # the workspace's test address

for received in anser.inbox.list_all(to="support@acme.com", read=False):  # from_="…" filters by sender
    email = anser.inbox.get(received["id"])
    print(email["stripped_text"])  # what the sender wrote, without the quoted history
    anser.inbox.reply(received["id"], {"text": "Thanks, we are on it."})
    anser.inbox.update(received["id"], read=True)  # read state is shared by the workspace

summary = anser.inbox.summary()  # unread counts, per receiving domain too
anser.inbox.mark(ids, read=True)  # or delete_many(ids), up to 100 at a time

anser.forwarding_rules.create(address="support@acme.com", forward_to="me@example.com")
```

## Webhooks

```python
from ansermail import WebhookVerificationError, verify_webhook


@app.post("/anser")
def anser_webhook():
    try:
        # the body exactly as it arrived, not parsed and serialized again
        event = verify_webhook(request.get_data(), request.headers, os.environ["ANSER_WEBHOOK_SECRET"])
    except WebhookVerificationError:
        return "", 400
    if event["type"] == "email.bounced":
        email_id = event["data"]["email"]["id"]  # the email, with its tags; the bounce details beside it
    return "", 204
```

## Errors

```python
from ansermail import AnserConnectionError, AnserError

try:
    anser.emails.send(params)
except AnserError as error:
    error.status_code  # 422
    error.code  # "validation_error", "domain_not_verified", "daily_quota_exceeded" …
    error.param  # the field it is about, e.g. "to[1]", or None
    error.message
    error.request_id  # look it up in the request logs
except AnserConnectionError:
    ...  # no answer: a timeout or the network
```

## Options

```python
Anser(
    "ms_…",  # default: ANSER_API_KEY
    base_url="https://mail.ruoyulab.dev",  # default: ANSER_BASE_URL, then the hosted service
    max_retries=2,  # rate limits always; server errors and lost connections only when safe to repeat
    timeout=60.0,  # per attempt, in seconds
    headers={},  # sent with every request
)

# and per call
anser.emails.get(email_id, timeout=5, max_retries=0)
```

The other resources follow the [API](https://mail.ruoyulab.dev/docs/api) (reference in Chinese): `domains`, `api_keys`,
`webhooks`, `suppressions`, `stats`, `recipients`, `usage` and `logs`.

## License

[MIT](LICENSE)
