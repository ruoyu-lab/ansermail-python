from __future__ import annotations

import base64
import builtins
import datetime
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, cast

from ._http import Http, Page, new_idempotency_key
from ._webhooks import verify_webhook
from .types import (
    ApiKey,
    BatchResult,
    CreatedApiKey,
    CreateTemplateParams,
    Deleted,
    DnsSetup,
    Domain,
    Email,
    EmailEvent,
    EmailSummary,
    ForwardingRule,
    ForwardParams,
    InboxSummary,
    ProviderStats,
    ReceivedAttachment,
    ReceivedEmail,
    ReceivedSummary,
    Recipient,
    RenderTemplateParams,
    ReplyParams,
    RequestLog,
    SendEmailParams,
    Stats,
    Suppression,
    Template,
    TemplateRender,
    TemplateSummary,
    TemplateVersion,
    TemplateVersionSummary,
    UpdateTemplateParams,
    Usage,
    Webhook,
    WebhookDelivery,
    WebhookEvent,
)


def _path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _time(value: str | datetime.datetime) -> str:
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            raise ValueError("scheduled_at needs a time zone, e.g. datetime.now(timezone.utc)")
        return value.isoformat()
    return value


def _wire(params: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(params)
    if "attachments" in body:
        body["attachments"] = [
            {**a, "content": base64.b64encode(a["content"]).decode()}
            if isinstance(a["content"], (bytes, bytearray))
            else dict(a)
            for a in body["attachments"]
        ]
    if "scheduled_at" in body:
        body["scheduled_at"] = _time(body["scheduled_at"])
    return body


def _page(answer: Any) -> Page[Any]:
    return Page(answer["data"], answer["has_more"])


class _Resource:
    def __init__(self, http: Http):
        self._http = http

    def _sending(self, path: str, body: Any, idempotency_key: str | None, options: Any) -> Any:
        """Sending calls always carry an idempotency key, so a retry never sends twice"""
        return self._http.request(
            "POST", path, body=body, idempotency_key=idempotency_key or new_idempotency_key(), **options
        )


class Emails(_Resource):
    def send(self, params: SendEmailParams, *, idempotency_key: str | None = None, **options: Any) -> EmailSummary:
        """Queue an email; it leaves within seconds, or at ``scheduled_at``"""
        return cast(EmailSummary, self._sending("/emails", _wire(params), idempotency_key, options))

    def send_batch(
        self,
        emails: Sequence[SendEmailParams],
        *,
        atomic: bool | None = None,
        idempotency_key: str | None = None,
        **options: Any,
    ) -> BatchResult:
        """Up to 100 emails: all or none, or with ``atomic=False`` each taken or refused on its own"""
        body: dict[str, Any] = {"emails": [_wire(e) for e in emails]}
        if atomic is not None:
            body["atomic"] = atomic
        return cast(BatchResult, self._sending("/emails/batch", body, idempotency_key, options))

    def get(self, email_id: str, **options: Any) -> Email:
        return cast(Email, self._http.request("GET", f"/emails/{_path(email_id)}", **options))

    def list(
        self,
        *,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        status: str | None = None,
        q: str | None = None,
        **options: Any,
    ) -> Page[EmailSummary]:
        """One page, newest first"""
        query = {"limit": limit, "after": after, "before": before, "status": status, "q": q}
        return _page(self._http.request("GET", "/emails", query=query, **options))

    def list_all(
        self, *, limit: int | None = None, status: str | None = None, q: str | None = None, **options: Any
    ) -> Iterator[EmailSummary]:
        """Every email matching, page after page"""
        return self._http.iterate("/emails", {"limit": limit, "status": status, "q": q}, **options)

    def events(self, email_id: str, **options: Any) -> builtins.list[EmailEvent]:
        """What happened to it, oldest first"""
        return cast(list[EmailEvent], self._http.request("GET", f"/emails/{_path(email_id)}/events", **options)["data"])

    def attachment(self, email_id: str, attachment_id: str, **options: Any) -> bytes:
        """An attachment's bytes; only while the email has not left yet"""
        path = f"/emails/{_path(email_id)}/attachments/{_path(attachment_id)}"
        return cast(bytes, self._http.request("GET", path, raw=True, **options))

    def update(self, email_id: str, *, scheduled_at: str | datetime.datetime, **options: Any) -> EmailSummary:
        """Move a scheduled email"""
        body = {"scheduled_at": _time(scheduled_at)}
        return cast(EmailSummary, self._http.request("PATCH", f"/emails/{_path(email_id)}", body=body, **options))

    def cancel(self, email_id: str, **options: Any) -> EmailSummary:
        """Cancel a scheduled email"""
        return cast(EmailSummary, self._http.request("POST", f"/emails/{_path(email_id)}/cancel", **options))


class Templates(_Resource):
    """Every call takes the template's id or its alias. Send with one: ``emails.send({"template": {...}})``."""

    def create(self, params: CreateTemplateParams, **options: Any) -> Template:
        """A new template with only a draft; publish it before sending with it"""
        return cast(Template, self._http.request("POST", "/templates", body=dict(params), **options))

    def get(self, template: str, **options: Any) -> Template:
        return cast(Template, self._http.request("GET", f"/templates/{_path(template)}", **options))

    def list(
        self,
        *,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        q: str | None = None,
        preview: bool | None = None,
        **options: Any,
    ) -> Page[TemplateSummary]:
        """One page, newest first; ``q`` matches the name and the alias, ``preview=True`` adds ``preview`` to each"""
        query = {"limit": limit, "after": after, "before": before, "q": q, "preview": preview}
        return _page(self._http.request("GET", "/templates", query=query, **options))

    def list_all(
        self, *, limit: int | None = None, q: str | None = None, preview: bool | None = None, **options: Any
    ) -> Iterator[TemplateSummary]:
        """Every template matching, page after page"""
        return self._http.iterate("/templates", {"limit": limit, "q": q, "preview": preview}, **options)

    def update(self, template: str, params: UpdateTemplateParams, **options: Any) -> Template:
        """Change the name, the alias or the draft; emails keep using the published version until you publish"""
        path = f"/templates/{_path(template)}"
        return cast(Template, self._http.request("PATCH", path, body=dict(params), **options))

    def delete(self, template: str, **options: Any) -> Deleted:
        """Emails already sent with it stay, with ``template: None``"""
        return cast(Deleted, self._http.request("DELETE", f"/templates/{_path(template)}", **options))

    def publish(self, template: str, **options: Any) -> Template:
        """Save the draft as the next version; emails use it from now on. Raises ``no_changes`` when nothing is new."""
        return cast(Template, self._http.request("POST", f"/templates/{_path(template)}/publish", **options))

    def duplicate(self, template: str, *, name: str | None = None, **options: Any) -> Template:
        """A copy of the draft, without the alias and unpublished; named "Copy of …" unless you name it"""
        body = {"name": name} if name is not None else {}
        path = f"/templates/{_path(template)}/duplicate"
        return cast(Template, self._http.request("POST", path, body=body, **options))

    def versions(self, template: str, **options: Any) -> builtins.list[TemplateVersionSummary]:
        """The published versions, newest first"""
        path = f"/templates/{_path(template)}/versions"
        return cast(list[TemplateVersionSummary], self._http.request("GET", path, **options)["data"])

    def version(self, template: str, version: int, **options: Any) -> TemplateVersion:
        path = f"/templates/{_path(template)}/versions/{version}"
        return cast(TemplateVersion, self._http.request("GET", path, **options))

    def restore(self, template: str, version: int, **options: Any) -> Template:
        """Put a version's content back into the draft; publish to send it again"""
        path = f"/templates/{_path(template)}/versions/{version}/restore"
        return cast(Template, self._http.request("POST", path, **options))

    def render(self, params: RenderTemplateParams, **options: Any) -> TemplateRender:
        """Render content with variables without storing anything; every field's problems come back together"""
        return cast(TemplateRender, self._http.request("POST", "/templates/render", body=dict(params), **options))


class Inbox(_Resource):
    """Emails sent to your domains (with receiving on) or to the workspace's test address"""

    def list(self, **params: Any) -> Page[ReceivedSummary]:
        """Filters: limit, after, before, to, from_, start_date, end_date, q, kind, status, in_reply_to_email_id,
        domain (of the receiving address), read (True for read emails only, False for unread)"""
        query, options = _split(params)
        return _page(self._http.request("GET", "/inbox", query=query, **options))

    def list_all(self, **params: Any) -> Iterator[ReceivedSummary]:
        query, options = _split(params)
        return self._http.iterate("/inbox", query, **options)

    def get(self, email_id: str, *, html_format: str | None = None, **options: Any) -> ReceivedEmail:
        """``html_format="cid"`` leaves inline images as ``cid:`` references"""
        path = f"/inbox/{_path(email_id)}"
        return cast(ReceivedEmail, self._http.request("GET", path, query={"html_format": html_format}, **options))

    def update(self, email_id: str, *, read: bool, **options: Any) -> ReceivedSummary:
        """Mark it read (keeping the first time) or unread; shared by the whole workspace"""
        path = f"/inbox/{_path(email_id)}"
        return cast(ReceivedSummary, self._http.request("PATCH", path, body={"read": read}, **options))

    def mark(self, ids: Sequence[str], *, read: bool, **options: Any) -> builtins.list[ReceivedSummary]:
        """Mark up to 100 emails read or unread; returns those marked (ids not found are skipped)"""
        body = {"ids": list(ids), "read": read}
        return cast(list[ReceivedSummary], self._http.request("POST", "/inbox/mark", body=body, **options)["data"])

    def delete(self, email_id: str, **options: Any) -> Deleted:
        """Deletes it with its attachments and raw message"""
        return cast(Deleted, self._http.request("DELETE", f"/inbox/{_path(email_id)}", **options))

    def delete_many(self, ids: Sequence[str], **options: Any) -> builtins.list[Deleted]:
        """Delete up to 100 emails; returns those deleted (ids not found are skipped)"""
        body = {"ids": list(ids)}
        return cast(list[Deleted], self._http.request("POST", "/inbox/delete", body=body, **options)["data"])

    def summary(self, **options: Any) -> InboxSummary:
        """How many emails, and unread ones, each receiving domain has"""
        return cast(InboxSummary, self._http.request("GET", "/inbox/summary", **options))

    def attachments(self, email_id: str, **params: Any) -> Page[ReceivedAttachment]:
        """Attachments with download links, in the order of the email"""
        query, options = _split(params)
        path = f"/inbox/{_path(email_id)}/attachments"
        return _page(self._http.request("GET", path, query=query, **options))

    def attachment(self, email_id: str, attachment_id: str, **options: Any) -> ReceivedAttachment:
        path = f"/inbox/{_path(email_id)}/attachments/{_path(attachment_id)}"
        return cast(ReceivedAttachment, self._http.request("GET", path, **options))

    def address(self, **options: Any) -> str | None:
        """The workspace's test address (``<name>+anything@…`` lands here too)"""
        return cast(str | None, self._http.request("GET", "/inbox/address", **options)["address"])

    def reply(
        self, email_id: str, params: ReplyParams, *, idempotency_key: str | None = None, **options: Any
    ) -> EmailSummary:
        """Answer it in the same thread (``In-Reply-To``, ``References``, ``Re:``); returns the email sent"""
        path = f"/inbox/{_path(email_id)}/reply"
        return cast(EmailSummary, self._sending(path, dict(params), idempotency_key, options))

    def forward(
        self, email_id: str, params: ForwardParams, *, idempotency_key: str | None = None, **options: Any
    ) -> EmailSummary:
        """Forward it with its attachments; returns the email sent"""
        path = f"/inbox/{_path(email_id)}/forward"
        return cast(EmailSummary, self._sending(path, dict(params), idempotency_key, options))


class ForwardingRules(_Resource):
    """Forward received emails to other mailboxes; a new destination confirms by a link first"""

    def list(self, **options: Any) -> builtins.list[ForwardingRule]:
        return cast(list[ForwardingRule], self._http.request("GET", "/forwarding-rules", **options)["data"])

    def create(self, *, address: str, forward_to: str, **options: Any) -> ForwardingRule:
        body = {"address": address, "forward_to": forward_to}
        return cast(ForwardingRule, self._http.request("POST", "/forwarding-rules", body=body, **options))

    def update(self, rule_id: str, *, enabled: bool, **options: Any) -> ForwardingRule:
        path = f"/forwarding-rules/{_path(rule_id)}"
        return cast(ForwardingRule, self._http.request("PATCH", path, body={"enabled": enabled}, **options))

    def delete(self, rule_id: str, **options: Any) -> Deleted:
        return cast(Deleted, self._http.request("DELETE", f"/forwarding-rules/{_path(rule_id)}", **options))

    def resend_confirmation(self, rule_id: str, **options: Any) -> ForwardingRule:
        """Send the confirmation email again (the old link stops working)"""
        path = f"/forwarding-rules/{_path(rule_id)}/confirmation"
        return cast(ForwardingRule, self._http.request("POST", path, **options))


class Domains(_Resource):
    def create(self, name: str, **options: Any) -> Domain:
        """Creates the SES identity; add the DNS records it returns"""
        return cast(Domain, self._http.request("POST", "/domains", body={"name": name}, **options))

    def list(self, **options: Any) -> builtins.list[Domain]:
        return cast(list[Domain], self._http.request("GET", "/domains", **options)["data"])

    def get(self, domain_id: str, **options: Any) -> Domain:
        return cast(Domain, self._http.request("GET", f"/domains/{_path(domain_id)}", **options))

    def update(
        self,
        domain_id: str,
        *,
        open_tracking: bool | None = None,
        click_tracking: bool | None = None,
        receiving: bool | None = None,
        **options: Any,
    ) -> Domain:
        changes = {"open_tracking": open_tracking, "click_tracking": click_tracking, "receiving": receiving}
        body = {k: v for k, v in changes.items() if v is not None}
        return cast(Domain, self._http.request("PATCH", f"/domains/{_path(domain_id)}", body=body, **options))

    def verify(self, domain_id: str, **options: Any) -> Domain:
        """Check SES and the DNS records again now"""
        return cast(Domain, self._http.request("POST", f"/domains/{_path(domain_id)}/verify", **options))

    def add_to_cloudflare(self, domain_id: str, token: str, **options: Any) -> DnsSetup:
        """Add the records that are not in effect yet at Cloudflare, with an API token that can edit the zone's DNS.

        The token is used for this call only and never stored.
        """
        path = f"/domains/{_path(domain_id)}/dns/cloudflare"
        return cast(DnsSetup, self._http.request("POST", path, body={"token": token}, **options))

    def delete(self, domain_id: str, **options: Any) -> Deleted:
        return cast(Deleted, self._http.request("DELETE", f"/domains/{_path(domain_id)}", **options))


class ApiKeys(_Resource):
    def create(
        self, name: str, *, permission: str | None = None, domain_id: str | None = None, **options: Any
    ) -> CreatedApiKey:
        fields = {"name": name, "permission": permission, "domain_id": domain_id}
        body = {k: v for k, v in fields.items() if v is not None}
        return cast(CreatedApiKey, self._http.request("POST", "/api-keys", body=body, **options))

    def list(self, **options: Any) -> builtins.list[ApiKey]:
        return cast(list[ApiKey], self._http.request("GET", "/api-keys", **options)["data"])

    def delete(self, key_id: str, **options: Any) -> Deleted:
        return cast(Deleted, self._http.request("DELETE", f"/api-keys/{_path(key_id)}", **options))


class Webhooks(_Resource):
    def create(
        self, endpoint: str, events: Sequence[str], *, description: str | None = None, **options: Any
    ) -> Webhook:
        """The answer has the ``secret`` for checking signatures"""
        body: dict[str, Any] = {"endpoint": endpoint, "events": list(events)}
        if description is not None:
            body["description"] = description
        return cast(Webhook, self._http.request("POST", "/webhooks", body=body, **options))

    def list(self, **options: Any) -> builtins.list[Webhook]:
        return cast(list[Webhook], self._http.request("GET", "/webhooks", **options)["data"])

    def get(self, webhook_id: str, **options: Any) -> Webhook:
        return cast(Webhook, self._http.request("GET", f"/webhooks/{_path(webhook_id)}", **options))

    def update(self, webhook_id: str, changes: Mapping[str, Any], **options: Any) -> Webhook:
        """``changes``: endpoint, events, description, enabled"""
        path = f"/webhooks/{_path(webhook_id)}"
        return cast(Webhook, self._http.request("PATCH", path, body=dict(changes), **options))

    def delete(self, webhook_id: str, **options: Any) -> Deleted:
        return cast(Deleted, self._http.request("DELETE", f"/webhooks/{_path(webhook_id)}", **options))

    def deliveries(self, webhook_id: str, **params: Any) -> Page[WebhookDelivery]:
        query, options = _split(params)
        path = f"/webhooks/{_path(webhook_id)}/deliveries"
        return _page(self._http.request("GET", path, query=query, **options))

    def test(self, webhook_id: str, **options: Any) -> WebhookDelivery:
        """Queue a ``webhook.test`` push"""
        return cast(WebhookDelivery, self._http.request("POST", f"/webhooks/{_path(webhook_id)}/test", **options))

    def verify(self, payload: str | bytes, headers: Mapping[str, Any], secret: str, **kwargs: Any) -> WebhookEvent:
        """Check a push you received and get its event; pass the raw body"""
        return verify_webhook(payload, headers, secret, **kwargs)


class Suppressions(_Resource):
    """Addresses that are never sent to"""

    def list(self, **params: Any) -> Page[Suppression]:
        """Filters: limit, after, before, q, reason (hard_bounce, complaint or manual)"""
        query, options = _split(params)
        return _page(self._http.request("GET", "/suppressions", query=query, **options))

    def list_all(self, **params: Any) -> Iterator[Suppression]:
        query, options = _split(params)
        return self._http.iterate("/suppressions", query, **options)

    def add(self, address: str, **options: Any) -> Suppression:
        return cast(Suppression, self._http.request("POST", "/suppressions", body={"address": address}, **options))

    def remove(self, address: str, **options: Any) -> Any:
        return self._http.request("DELETE", f"/suppressions/{_path(address)}", **options)


class StatsApi(_Resource):
    def get(self, *, days: int | None = None, **options: Any) -> Stats:
        """Per UTC day, with totals and rates"""
        return cast(Stats, self._http.request("GET", "/stats", query={"days": days}, **options))

    def providers(self, *, days: int | None = None, **options: Any) -> list[ProviderStats]:
        """The same period per mailbox provider (Gmail, QQ, Outlook…), busiest first"""
        answer = self._http.request("GET", "/stats/providers", query={"days": days}, **options)
        return cast(list[ProviderStats], answer["data"])


class Recipients(_Resource):
    def get(self, address: str, **options: Any) -> Recipient:
        """Why someone may not be getting your emails"""
        return cast(Recipient, self._http.request("GET", f"/recipients/{_path(address)}", **options))


class UsageApi(_Resource):
    def get(self, **options: Any) -> Usage:
        """How much of the workspace's quotas is used"""
        return cast(Usage, self._http.request("GET", "/usage", **options))


class Logs(_Resource):
    """Your API requests of the last 7 days"""

    def list(self, **params: Any) -> Page[RequestLog]:
        """Filters: limit, after, before, status ("succeeded" or "failed")"""
        query, options = _split(params)
        return _page(self._http.request("GET", "/logs", query=query, **options))

    def list_all(self, **params: Any) -> Iterator[RequestLog]:
        query, options = _split(params)
        return self._http.iterate("/logs", query, **options)

    def get(self, log_id: str, **options: Any) -> RequestLog:
        """With the request and response bodies"""
        return cast(RequestLog, self._http.request("GET", f"/logs/{_path(log_id)}", **options))


_OPTIONS = ("timeout", "max_retries")


def _split(params: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Query filters and request options; ``from_`` is ``from`` (a Python keyword)"""
    query = {("from" if k == "from_" else k): v for k, v in params.items() if k not in _OPTIONS}
    return query, {k: v for k, v in params.items() if k in _OPTIONS}
