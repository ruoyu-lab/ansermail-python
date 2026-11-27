"""Request and response shapes, one to one with the HTTP API (snake_case, as on the wire).

Responses are plain dicts; these TypedDicts describe them for type checkers and editors. Times are ISO 8601
strings in UTC; ids are UUIDv7 strings.
"""

from __future__ import annotations

import datetime
from typing import Any, Literal, TypedDict

#: ``{"category": "welcome"}``: up to 50; names and values are letters, digits, ``_`` and ``-``, up to 256 each
Tags = dict[str, str]


class _MailboxRequired(TypedDict):
    email: str


class Mailbox(_MailboxRequired, total=False):
    name: str


#: ``"amy@example.com"``, ``"Amy <amy@example.com>"``, or the name apart: ``{"email": "amy@example.com", "name": "Amy"}``
Address = str | Mailbox
Addresses = Address | list[Address]


class _AttachmentRequired(TypedDict):
    filename: str
    #: base64 text, or raw bytes (encoded for you)
    content: str | bytes


class Attachment(_AttachmentRequired, total=False):
    content_type: str
    #: set it to show the attachment inline: ``<img src="cid:…">``
    content_id: str


_SendEmailRequired = TypedDict("_SendEmailRequired", {"from": Address, "to": Addresses, "subject": str})


class SendEmailParams(_SendEmailRequired, total=False):
    #: ``html`` or ``text``, at least one
    html: str
    text: str
    cc: Addresses
    bcc: Addresses
    reply_to: Addresses
    headers: dict[str, str]
    #: up to 30 MB together
    attachments: list[Attachment]
    tags: Tags
    #: send later (up to 30 days)
    scheduled_at: str | datetime.datetime


EmailStatus = Literal[
    "scheduled",
    "queued",
    "sending",
    "sent",
    "delivered",
    "delivery_delayed",
    "bounced",
    "complained",
    "failed",
    "canceled",
    "suppressed",
]

EmailSummary = TypedDict(
    "EmailSummary",
    {
        "object": Literal["email"],
        "id": str,
        "from": str,
        "to": list[str],
        "subject": str,
        "status": EmailStatus,
        "tags": Tags,
        "created_at": str,
        "scheduled_at": str | None,
        "sent_at": str | None,
    },
)


class BatchError(TypedDict):
    #: which email, from 0
    index: int
    code: str
    message: str
    param: str | None


class BatchResult(TypedDict):
    object: Literal["batch"]
    #: one per email, in order; None for one that was refused
    data: list[EmailSummary | None]
    #: why the refused ones were refused; always empty when atomic
    errors: list[BatchError]


class EmailAttachment(TypedDict):
    id: str
    filename: str
    content_type: str
    content_id: str | None
    size: int
    #: false once the email is sent, failed or canceled: only the name and size are kept
    downloadable: bool


class Email(EmailSummary):
    cc: list[str]
    bcc: list[str]
    reply_to: list[str]
    html: str | None
    text: str | None
    headers: dict[str, str]
    attachments: list[EmailAttachment]
    attempts: int
    last_error: str | None
    provider_message_id: str | None


class EmailEvent(TypedDict):
    object: Literal["email_event"]
    id: str
    type: str
    data: dict[str, Any]
    occurred_at: str


class Deleted(TypedDict):
    object: str
    id: str
    deleted: Literal[True]


# ---------------------------------------------------------------- the inbox

Verdict = Literal["pass", "fail", "gray", "processing_failed", "unknown"]


class Authentication(TypedDict):
    spf: Verdict
    dkim: Verdict
    dmarc: Verdict


class ReceivedAttachmentMeta(TypedDict):
    id: str
    filename: str
    content_type: str
    content_disposition: Literal["attachment", "inline"]
    content_id: str | None
    size: int


class ReceivedAttachment(ReceivedAttachmentMeta):
    object: Literal["attachment"]
    #: valid for an hour; fetch the attachment again for a new one
    download_url: str
    expires_at: str


_ReceivedFrom = TypedDict("_ReceivedFrom", {"from": str})


class ReceivedSummary(_ReceivedFrom):
    object: Literal["received_email"]
    id: str
    to: list[str]
    created_at: str
    subject: str
    bcc: list[str]
    cc: list[str]
    reply_to: list[str]
    message_id: str | None
    attachments: list[ReceivedAttachmentMeta]
    status: Literal["received", "blocked", "over_quota"]
    kind: Literal["message", "reply", "auto_reply", "bounce"]
    received_for: list[str]
    from_header: str | None
    in_reply_to_email_id: str | None
    spam_verdict: Verdict
    virus_verdict: Verdict
    authentication: Authentication
    preview: str | None
    size: int


class ReceivedEmail(ReceivedSummary):
    html: str | None
    html_format: Literal["data_uri", "cid"]
    text: str | None
    headers: dict[str, str]
    raw: dict[str, str] | None
    stripped_text: str | None
    in_reply_to: str | None
    references: list[str]
    forwards: list[dict[str, str | None]]
    sent_at: str | None


ReplyParams = TypedDict(
    "ReplyParams",
    {
        "from": Address,
        "to": Addresses,
        "cc": Addresses,
        "bcc": Addresses,
        "reply_all": bool,
        "subject": str,
        "html": str,
        "text": str,
        "tags": Tags,
    },
    total=False,
)

_ForwardRequired = TypedDict("_ForwardRequired", {"from": Address, "to": Addresses})


class ForwardParams(_ForwardRequired, total=False):
    #: default True: forward as it is; False: your html / text with the original below
    passthrough: bool
    html: str
    text: str
    tags: Tags


class ForwardingRule(TypedDict):
    object: Literal["forwarding_rule"]
    id: str
    address: str
    domain_id: str
    forward_to: str
    enabled: bool
    status: Literal["active", "pending_confirmation", "confirmation_expired"]
    confirmed_at: str | None
    confirmation_sent_at: str
    created_at: str


# ---------------------------------------------------------------- domains, keys, webhooks, suppressions


class _DnsRecordBase(TypedDict):
    #: ``mx`` and ``spf`` are for the bounce subdomain; ``receiving`` brings the domain's email in
    purpose: Literal["dkim", "mx", "spf", "dmarc", "receiving"]
    name: str
    type: Literal["CNAME", "TXT", "MX"]
    value: str
    priority: int | None
    required: bool
    status: Literal["verified", "pending", "failed", "not_started"]


class DnsRecord(_DnsRecordBase, total=False):
    #: ``receiving`` only: other MX servers on the domain that may get the email first
    conflicts: list[str]


class Domain(TypedDict):
    object: Literal["domain"]
    id: str
    name: str
    region: str
    status: Literal["not_started", "pending", "verified", "failed", "temporary_failure"]
    created_at: str
    checked_at: str | None
    verified_at: str | None
    open_tracking: bool
    click_tracking: bool
    receiving: bool
    records: list[DnsRecord]


class ApiKey(TypedDict):
    object: Literal["api_key"]
    id: str
    name: str
    #: ``full``: everything; ``send``: sending only, optionally from one domain
    permission: Literal["full", "send"]
    domain_id: str | None
    token_prefix: str
    created_at: str
    last_used_at: str | None


class CreatedApiKey(ApiKey):
    #: shown only this once
    token: str


class _WebhookBase(TypedDict):
    object: Literal["webhook"]
    id: str
    endpoint: str
    events: list[str]
    description: str | None
    enabled: bool
    created_at: str


class Webhook(_WebhookBase, total=False):
    #: ``whsec_…``; returned by create and get, not by list
    secret: str


class WebhookDelivery(TypedDict):
    object: Literal["webhook_delivery"]
    id: str
    event_type: str
    status: Literal["pending", "succeeded", "failed"]
    attempts: int
    response_status: int | None
    last_error: str | None
    payload: Any
    created_at: str
    delivered_at: str | None
    next_attempt_at: str | None


class WebhookEvent(TypedDict):
    """A verified push: ``email.delivered``, ``email.received``, … and its data.

    ``data["email"]`` is the email it is about (with its tags; for ``email.received``, the email as the inbox lists
    it); an email event's own fields (bounce details, the clicked link and so on) are beside it.
    """

    type: str
    created_at: str
    data: dict[str, Any]


class Suppression(TypedDict):
    object: Literal["suppression"]
    id: str
    address: str
    reason: Literal["hard_bounce", "complaint", "manual"]
    email_id: str | None
    created_at: str


# ---------------------------------------------------------------- statistics, usage, logs


class Counts(TypedDict):
    sent: int
    delivered: int
    bounced: int
    complained: int
    failed: int
    opened: int
    clicked: int


class DayCounts(Counts):
    date: str


class Stats(TypedDict):
    object: Literal["stats"]
    days: list[DayCounts]
    totals: Counts
    rates: dict[str, float | None]


class ProviderStats(TypedDict):
    object: Literal["provider_stats"]
    provider: str
    name: str
    sent: int
    delivered: int
    delayed: int
    bounced: int
    complained: int
    rates: dict[str, float | None]
    delivery_times: list[dict[str, int | None]]


class Recipient(TypedDict):
    object: Literal["recipient"]
    address: str
    domain: str
    provider: str | None
    provider_name: str | None
    accepts_mail: bool | None
    did_you_mean: str | None
    suppression: dict[str, Any] | None
    recently_bounced: bool
    emails: list[dict[str, Any]]
    rejected_requests: list[dict[str, Any]]


class Quota(TypedDict):
    used: int
    #: None: no limit
    limit: int | None
    resets_at: str


class Usage(TypedDict):
    object: Literal["usage"]
    today: Quota
    month: Quota
    domains: dict[str, int | None]
    attachments: Quota
    receiving: dict[str, dict[str, Any]]
    retention_days: int | None
    max_retention_days: int | None
    paused_at: str | None
    pause_reason: Literal["bounce_rate", "complaint_rate", "admin"] | None


class RequestLog(TypedDict):
    object: Literal["request_log"]
    id: str
    method: str
    path: str
    status: int
    duration_ms: int
    api_key: dict[str, str] | None
    user_agent: str | None
    created_at: str
    request_body: str | None
    response_body: str | None
