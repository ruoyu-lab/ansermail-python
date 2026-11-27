"""The 鸿雁 / Anser SDK: send and receive email through the HTTP API.

from ansermail import Anser

anser = Anser("ms_…")
email = anser.emails.send({
    "from": "Acme <hello@acme.com>",
    "to": {"email": "amy@example.com", "name": "Amy"},
    "subject": "Welcome",
    "html": "<p>Hi Amy</p>",
    "tags": {"category": "welcome"},
})
"""

from __future__ import annotations

from collections.abc import Mapping

from ._errors import AnserConnectionError, AnserError, WebhookVerificationError
from ._http import DEFAULT_BASE_URL, VERSION, Http, Page
from ._resources import (
    ApiKeys,
    Domains,
    Emails,
    ForwardingRules,
    Inbox,
    Logs,
    Recipients,
    StatsApi,
    Suppressions,
    UsageApi,
    Webhooks,
)
from ._webhooks import verify_webhook

__version__ = VERSION
__all__ = [
    "DEFAULT_BASE_URL",
    "Anser",
    "AnserConnectionError",
    "AnserError",
    "Page",
    "WebhookVerificationError",
    "verify_webhook",
]


class Anser:
    """``Anser("ms_…")``, or ``Anser()`` with ``ANSER_API_KEY`` set.

    ``max_retries`` (default 2) covers network errors, rate limits and server errors; ``timeout`` is per
    attempt, in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
    ):
        http = Http(api_key, base_url, max_retries, timeout, headers)
        self.emails = Emails(http)
        self.inbox = Inbox(http)
        self.forwarding_rules = ForwardingRules(http)
        self.domains = Domains(http)
        self.api_keys = ApiKeys(http)
        self.webhooks = Webhooks(http)
        self.suppressions = Suppressions(http)
        self.stats = StatsApi(http)
        self.recipients = Recipients(http)
        self.usage = UsageApi(http)
        self.logs = Logs(http)
