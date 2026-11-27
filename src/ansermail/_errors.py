from __future__ import annotations

from collections.abc import Mapping


class AnserError(Exception):
    """The API answered with an error.

    ``code`` is the API's error code (``not_found``, ``validation_error``, …), ``param`` the field it is about
    (``to[1]``, ``attachments[0].content``) when there is one, and ``request_id`` what to look up in the request logs.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str],
        param: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.param = param
        self.request_id = headers.get("x-request-id")
        self.headers = headers

    def __repr__(self) -> str:
        return f"AnserError({self.status_code}, {self.code!r}, {self.message!r}, param={self.param!r})"


class AnserConnectionError(Exception):
    """No answer: the connection failed or the request timed out."""


class WebhookVerificationError(Exception):
    """A webhook push whose signature, timestamp or headers are wrong."""
