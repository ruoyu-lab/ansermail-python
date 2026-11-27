from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Generic, TypeVar

from ._errors import AnserConnectionError, AnserError

VERSION = "0.1.0"
DEFAULT_BASE_URL = "https://mail.ruoyulab.dev"

T = TypeVar("T")


class Page(Generic[T]):
    """One page of a list. Iterating it goes through ``data``."""

    def __init__(self, data: list[T], has_more: bool):
        self.data = data
        self.has_more = has_more

    def __iter__(self) -> Iterator[T]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return f"Page({len(self.data)} items, has_more={self.has_more})"


def new_idempotency_key() -> str:
    return f"anser-{uuid.uuid4()}"


class Http:
    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        max_retries: int,
        timeout: float,
        headers: Mapping[str, str] | None,
    ):
        key = api_key or os.environ.get("ANSER_API_KEY")
        if not key:
            raise ValueError("Missing API key: pass api_key or set ANSER_API_KEY.")
        self.api_key = key
        self.base_url = (base_url or os.environ.get("ANSER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout
        self.headers = dict(headers or {})

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotency_key: str | None = None,
        raw: bool = False,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Any:
        url = f"{self.base_url}/v1{path}"
        params = {k: _query_value(v) for k, v in (query or {}).items() if v is not None}
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            **self.headers,
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"ansermail-python/{VERSION}",
            "Accept": "*/*" if raw else "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        retries = self.max_retries if max_retries is None else max_retries
        # A POST runs again only when the server can tell it is the same request
        safe = method != "POST" or bool(idempotency_key)

        attempt = 0
        while True:
            try:
                status, res_headers, content = self._send(method, url, data, headers, timeout or self.timeout)
            except AnserConnectionError:
                if not safe or attempt >= retries:
                    raise
                time.sleep(_backoff(attempt))
                attempt += 1
                continue
            if 200 <= status < 300:
                if raw:
                    return content
                return json.loads(content) if content else None
            error = _to_error(status, res_headers, content)
            if attempt < retries and _retryable(error, safe):
                time.sleep(_retry_after(res_headers) or _backoff(attempt))
                attempt += 1
                continue
            raise error

    def iterate(self, path: str, query: Mapping[str, Any], **options: Any) -> Iterator[Any]:
        """Every page of a list, one item at a time"""
        params = dict(query)
        while True:
            page = self.request("GET", path, query=params, **options)
            yield from page["data"]
            if not page["has_more"] or not page["data"]:
                return
            params["after"] = page["data"][-1]["id"]

    def _send(
        self, method: str, url: str, data: bytes | None, headers: dict[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status, _lower(res.headers.items()), res.read()
        except urllib.error.HTTPError as error:
            return error.code, _lower(error.headers.items()), error.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise AnserConnectionError(f"Timed out after {timeout} s") from error
            raise AnserConnectionError(f"Could not reach {urllib.parse.urlsplit(url).netloc}") from error


def _lower(items: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {name.lower(): value for name, value in items}


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(value)
    return str(value)


def _to_error(status: int, headers: Mapping[str, str], content: bytes) -> AnserError:
    try:
        error = json.loads(content)["error"]
        if isinstance(error.get("code"), str) and isinstance(error.get("message"), str):
            param = error.get("param")
            return AnserError(
                status, error["code"], error["message"], headers, param if isinstance(param, str) else None
            )
    except (ValueError, KeyError, TypeError, AttributeError):
        pass  # not JSON: a proxy in between answered
    text = content.decode(errors="replace")[:500]
    return AnserError(status, "http_error", text or f"HTTP {status}", headers)


def _retryable(error: AnserError, safe: bool) -> bool:
    """Turned away before it ran (a rate limit, the same key still running), or a server error on a safe call"""
    if error.status_code == 429:
        return error.code == "rate_limit_exceeded"
    if error.status_code == 409:
        return error.code == "idempotency_key_in_use"
    return safe and error.status_code in (500, 502, 503, 504)


def _retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        seconds = float(headers.get("retry-after") or "")
    except ValueError:
        return None
    return min(seconds, 60.0) if seconds > 0 else None


def _backoff(attempt: int) -> float:
    """0.5 s, 1 s, 2 s … up to 8 s, give or take a quarter"""
    return min(0.5 * 2.0**attempt, 8.0) * random.uniform(0.75, 1.25)
