from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any, cast

from ._errors import WebhookVerificationError
from .types import WebhookEvent


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        value = next((v for k, v in headers.items() if k.lower() == name), None)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value


def verify_webhook(
    payload: str | bytes,
    headers: Mapping[str, Any],
    secret: str,
    *,
    tolerance: int = 300,
    now: float | None = None,
) -> WebhookEvent:
    """Check a webhook push (Standard Webhooks) and return its event.

    ``payload`` must be the raw request body, before any JSON parsing. ``tolerance`` is how old (or how far
    ahead) a push may be, in seconds.
    """
    msg_id = _header(headers, "webhook-id")
    timestamp = _header(headers, "webhook-timestamp")
    signatures = _header(headers, "webhook-signature")
    if not msg_id or not timestamp or not signatures:
        raise WebhookVerificationError("Missing webhook-id, webhook-timestamp or webhook-signature.")
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise WebhookVerificationError("The webhook timestamp is not a number.") from None
    if abs((time.time() if now is None else now) - sent_at) > tolerance:
        raise WebhookVerificationError("The webhook timestamp is too old or too far ahead.")
    body = payload.decode() if isinstance(payload, bytes) else payload
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except binascii.Error:
        raise WebhookVerificationError("The webhook secret is not valid.") from None
    digest = hmac.new(key, f"{msg_id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    for signature in signatures.split(" "):
        version, _, value = signature.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return cast(WebhookEvent, json.loads(body))
    raise WebhookVerificationError("The webhook signature does not match.")
