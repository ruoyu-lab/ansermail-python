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


class _SendEmailOptions(TypedDict, total=False):
    """What every email takes, with or without a template"""

    cc: Addresses
    bcc: Addresses
    reply_to: Addresses
    headers: dict[str, str]
    #: up to 30 MB together
    attachments: list[Attachment]
    tags: Tags
    #: send later (up to 30 days)
    scheduled_at: str | datetime.datetime


_WithContentRequired = TypedDict("_WithContentRequired", {"from": Address, "to": Addresses, "subject": str})


class SendEmailWithContent(_WithContentRequired, _SendEmailOptions, total=False):
    """Content written by you: ``from``, ``subject``, and ``html`` or ``text`` (at least one)"""

    html: str
    text: str


class _TemplateRefRequired(TypedDict):
    #: the template's id or alias
    id: str


class TemplateRef(_TemplateRefRequired, total=False):
    """A template's latest published version, rendered with ``variables``"""

    #: up to 1 MB of JSON; every variable the template prints must be here, or the email is refused
    variables: dict[str, Any]


class _WithTemplateRequired(TypedDict):
    to: Addresses
    template: TemplateRef


_WithTemplateOverrides = TypedDict("_WithTemplateOverrides", {"from": Address, "subject": str}, total=False)


class SendEmailWithTemplate(_WithTemplateRequired, _WithTemplateOverrides, _SendEmailOptions):
    """Content from a template; ``from``, ``subject`` and ``reply_to`` given here win over the template's"""


SendEmailParams = SendEmailWithContent | SendEmailWithTemplate


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


class EmailTemplate(TypedDict):
    id: str
    version: int


class Email(EmailSummary):
    cc: list[str]
    bcc: list[str]
    reply_to: list[str]
    html: str | None
    text: str | None
    headers: dict[str, str]
    attachments: list[EmailAttachment]
    #: the template and version it was sent with; None when it had its own content or the template was deleted
    template: EmailTemplate | None
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
    read_at: str | None
    """When someone in the workspace read it; None while unread. Shared by the whole workspace"""


class InboxDomain(TypedDict):
    """One receiving domain on the inbox's front page"""

    object: Literal["inbox_domain"]
    domain: str
    test_address: bool
    receiving: bool
    total: int
    unread: int
    last_received_at: str | None


class InboxSummary(TypedDict):
    """The inbox counted by receiving domain; the totals count each email once"""

    object: Literal["inbox_summary"]
    total: int
    unread: int
    last_received_at: str | None
    domains: list[InboxDomain]


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
    #: ``ownership`` (a TXT at ``_anser.<domain>``) proves the domain belongs to this workspace;
    #: ``mx`` and ``spf`` are for the bounce subdomain; ``receiving`` brings the domain's email in
    purpose: Literal["ownership", "dkim", "mx", "spf", "dmarc", "receiving"]
    name: str
    type: Literal["CNAME", "TXT", "MX"]
    value: str
    priority: int | None
    required: bool
    status: Literal["verified", "pending", "failed", "not_started"]


class DnsRecord(_DnsRecordBase, total=False):
    #: ``receiving`` only: other MX servers on the domain that may get the email first
    conflicts: list[str]


class DnsHost(TypedDict):
    #: the zone the records go into: ``acme.com`` for ``mail.acme.com``
    zone: str
    #: ``None`` when not recognized
    provider: Literal["cloudflare", "aliyun", "dnspod", "godaddy", "namecheap", "route53"] | None


class Domain(TypedDict):
    object: Literal["domain"]
    id: str
    name: str
    #: the server's SES region, the same for every domain
    region: str
    status: Literal["not_started", "pending", "verified", "failed", "temporary_failure"]
    created_at: str
    checked_at: str | None
    verified_at: str | None
    open_tracking: bool
    click_tracking: bool
    receiving: bool
    records: list[DnsRecord]
    #: where the domain's DNS is hosted, from its NS records; ``None`` until found
    dns: DnsHost | None


class _DnsSetupResultBase(TypedDict):
    purpose: Literal["ownership", "dkim", "mx", "spf", "dmarc", "receiving"]
    type: Literal["CNAME", "TXT", "MX"]
    name: str
    #: ``exists``: already there, left alone; ``updated``: already there but proxied, now DNS only;
    #: ``conflict``: another value at that name, left alone; ``failed``: Cloudflare refused
    outcome: Literal["created", "exists", "updated", "conflict", "failed"]


class DnsSetupResult(_DnsSetupResultBase, total=False):
    #: ``conflict`` only: the values already at that name
    existing: list[str]
    #: ``failed`` only: what Cloudflare said
    message: str


class DnsSetup(TypedDict):
    object: Literal["dns_setup"]
    provider: Literal["cloudflare"]
    #: the Cloudflare zone the records went into
    zone: str
    results: list[DnsSetupResult]
    #: the domain, checked again
    domain: Domain


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
    #: until when a new workspace has a lower daily quota (already in ``today.limit``); None when not
    ramp_until: str | None
    today: Quota
    month: Quota
    domains: dict[str, int | None]
    attachments: Quota
    receiving: dict[str, dict[str, Any]]
    retention_days: int | None
    max_retention_days: int | None
    paused_at: str | None
    pause_reason: Literal["bounce_rate", "complaint_rate", "owner_reputation", "admin"] | None


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


# ---------------------------------------------------------------- templates

#: A draft or a published version. ``subject``, ``html`` and ``text`` are Handlebars; ``from`` and ``reply_to`` are used
#: when the email does not give its own; ``variables`` are the top-level ones it uses (``user`` for ``{{user.name}}``).
TemplateBody = TypedDict(
    "TemplateBody",
    {
        "subject": str | None,
        "html": str | None,
        "text": str | None,
        "from": str | None,
        "reply_to": list[str],
        "variables": list[str],
    },
)


class PublishedTemplateBody(TemplateBody):
    version: int
    published_at: str


class Template(TypedDict):
    object: Literal["template"]
    id: str
    name: str
    #: send and look it up by this instead of the id
    alias: str | None
    #: what edits change; never sent
    draft: TemplateBody
    #: the latest published version, the one emails use; None until first published
    published: PublishedTemplateBody | None
    #: the draft differs from the published version (or nothing is published yet)
    has_unpublished_changes: bool
    created_at: str
    updated_at: str


class TemplateSummaryPreview(TypedDict):
    """The draft rendered with ``suggested_variables``, for thumbnails. A field with a syntax error is ``None`` and
    ``unavailable`` is ``"error"``; when html or text is over 128 KB nothing is rendered (``"too_large"``)."""

    html: str | None
    text: str | None
    unavailable: Literal["error", "too_large"] | None


class _TemplateSummaryRequired(TypedDict):
    object: Literal["template"]
    id: str
    name: str
    alias: str | None
    subject: str | None
    published_version: int | None
    published_at: str | None
    has_unpublished_changes: bool
    created_at: str
    updated_at: str


class TemplateSummary(_TemplateSummaryRequired, total=False):
    """A template in a list: without the content; ``subject`` is the draft's"""

    #: only when listed with ``preview=True``
    preview: TemplateSummaryPreview


_CreateTemplateRequired = TypedDict("_CreateTemplateRequired", {"name": str})

#: ``alias``: 1–100 letters, digits, ``.``, ``_`` and ``-``, starting with a letter or digit, unique in the workspace.
#: ``html`` and ``text`` up to 1 MB each; publishing needs at least one. ``from`` and ``reply_to`` are used when the
#: email does not give its own.
_TemplateFields = TypedDict(
    "_TemplateFields",
    {
        "alias": str | None,
        "subject": str | None,
        "html": str | None,
        "text": str | None,
        "from": Address | None,
        "reply_to": Addresses | None,
    },
    total=False,
)


class CreateTemplateParams(_CreateTemplateRequired, _TemplateFields):
    pass


class UpdateTemplateParams(_TemplateFields, total=False):
    """Changes the draft only; ``None`` (or ``""``) clears a field"""

    name: str


class RenderTemplateParams(TypedDict, total=False):
    """Content to try out: nothing is stored"""

    subject: str | None
    html: str | None
    text: str | None
    variables: dict[str, Any]


class TemplateVersionSummary(TypedDict):
    object: Literal["template_version"]
    template_id: str
    version: int
    subject: str | None
    published_at: str
    #: the email of whoever published it from the dashboard; None through the API
    published_by: str | None


_TemplateVersionBody = TypedDict(
    "_TemplateVersionBody", {"html": str | None, "text": str | None, "from": str | None, "reply_to": list[str]}
)


class TemplateVersion(TemplateVersionSummary, _TemplateVersionBody):
    pass


class TemplateRenderError(TypedDict):
    field: Literal["subject", "html", "text"]
    #: from 1; None when not known
    line: int | None
    #: ``syntax``: it does not parse; ``missing_variable``: printed but not given; ``render``: a helper failed or it
    #: grew too large
    code: Literal["syntax", "missing_variable", "render"]
    message: str


class TemplateRender(TypedDict):
    object: Literal["template_render"]
    #: None for a field not given or with an error
    subject: str | None
    html: str | None
    text: str | None
    variables: list[str]
    #: sample variables shaped like the template uses them (``{{user.name}}`` is a dict, ``{{#each items}}`` a
    #: one-item list); a starting point to edit, rendering with it misses nothing
    suggested_variables: dict[str, Any]
    errors: list[TemplateRenderError]
