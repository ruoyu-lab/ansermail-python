"""The client against a small local server that answers what each test scripts."""

from __future__ import annotations

import base64
import datetime
import json
import os
import pathlib
import threading
import time
import unittest
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ansermail import Anser, AnserConnectionError, AnserError, WebhookVerificationError, verify_webhook

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures" / "webhook.json").read_text())

Answer = tuple[int, dict[str, str], Any]


class Quiet(ThreadingHTTPServer):
    """A client that gave up (the timeout test) is not a failure"""

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class Stub:
    """Records requests; ``answer`` decides each reply (status, headers, JSON body or bytes)"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.answer: Callable[[dict[str, Any]], Answer] = lambda req: (201, {}, {"object": "email", "id": "e1"})
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def handle_one(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                req = {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(raw) if raw else None,
                }
                stub.requests.append(req)
                status, headers, body = stub.answer(req)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_DELETE = handle_one

            def log_message(self, *args: Any) -> None:
                pass

        self.server = Quiet(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def error(status: int, code: str, headers: dict[str, str] | None = None, param: str | None = None) -> Answer:
    return status, headers or {}, {"error": {"code": code, "message": f"{code} happened", "param": param}}


class ClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = Stub()
        self.anser = Anser("ms_test", base_url=self.stub.url + "/")

    def tearDown(self) -> None:
        self.stub.close()

    def test_sends_with_a_key_bytes_and_a_time(self) -> None:
        at = datetime.datetime(2026, 12, 1, 9, 0, tzinfo=datetime.timezone.utc)
        sent = self.anser.emails.send(
            {
                "from": {"email": "hello@acme.com", "name": "Acme"},
                "to": "amy@example.com",
                "subject": "Hi",
                "text": "Hi",
                "attachments": [{"filename": "a.txt", "content": "你好".encode()}],
                "tags": {"category": "welcome"},
                "scheduled_at": at,
            }
        )
        self.assertEqual(sent, {"object": "email", "id": "e1"})
        req = self.stub.requests[0]
        self.assertEqual((req["method"], req["path"]), ("POST", "/v1/emails"))
        self.assertEqual(req["body"]["from"], {"email": "hello@acme.com", "name": "Acme"})
        self.assertEqual(req["body"]["tags"], {"category": "welcome"})
        self.assertEqual(req["headers"]["authorization"], "Bearer ms_test")
        self.assertTrue(req["headers"]["idempotency-key"].startswith("anser-"))
        self.assertTrue(req["headers"]["user-agent"].startswith("ansermail-python/"))
        self.assertEqual(req["body"]["attachments"][0]["content"], base64.b64encode("你好".encode()).decode())
        self.assertEqual(req["body"]["scheduled_at"], "2026-12-01T09:00:00+00:00")

    def test_retries_a_send_with_the_same_key(self) -> None:
        answers = iter([error(503, "internal_error"), (201, {}, {"id": "e1"})])
        self.stub.answer = lambda req: next(answers)
        self.assertEqual(
            self.anser.emails.send({"from": "a@acme.com", "to": "b@x.com", "subject": "s", "text": "t"})["id"], "e1"
        )
        keys = [r["headers"]["idempotency-key"] for r in self.stub.requests]
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])

    def test_never_repeats_a_create_without_a_key(self) -> None:
        self.stub.answer = lambda req: error(503, "internal_error")
        with self.assertRaises(AnserError) as caught:
            self.anser.domains.create("acme.com")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(len(self.stub.requests), 1)

    def test_waits_out_a_rate_limit_but_not_a_quota(self) -> None:
        answers = iter([error(429, "rate_limit_exceeded", {"retry-after": "1"}), (200, {}, {"object": "usage"})])
        self.stub.answer = lambda req: next(answers)
        started = time.monotonic()
        self.assertEqual(self.anser.usage.get(), {"object": "usage"})
        self.assertGreaterEqual(time.monotonic() - started, 0.9)

        self.stub.requests.clear()
        self.stub.answer = lambda req: error(429, "daily_quota_exceeded")
        with self.assertRaises(AnserError) as caught:
            self.anser.emails.send({"from": "a@acme.com", "to": "b@x.com", "subject": "s", "text": "t"})
        self.assertEqual(caught.exception.code, "daily_quota_exceeded")
        self.assertEqual(len(self.stub.requests), 1)

    def test_errors(self) -> None:
        self.stub.answer = lambda req: error(422, "validation_error", {"x-request-id": "r1"}, param="to[1]")
        with self.assertRaises(AnserError) as caught:
            self.anser.emails.send({"from": "a@acme.com", "to": ["b@x.com", "nope"], "subject": "s", "text": "t"})
        self.assertEqual((caught.exception.status_code, caught.exception.code), (422, "validation_error"))
        self.assertEqual((caught.exception.param, caught.exception.request_id), ("to[1]", "r1"))
        self.assertEqual(str(caught.exception), "validation_error happened")

        self.stub.answer = lambda req: (502, {"content-type": "text/html"}, b"<h1>Bad Gateway</h1>")
        with self.assertRaises(AnserError) as caught:
            Anser("ms_test", base_url=self.stub.url, max_retries=0).usage.get()
        self.assertEqual((caught.exception.status_code, caught.exception.code), (502, "http_error"))

    def test_sends_a_batch(self) -> None:
        result = {"object": "batch", "data": [None], "errors": [{"index": 0, "code": "domain_not_verified"}]}
        self.stub.answer = lambda req: (200, {}, result)
        email = {"from": "a@other.com", "to": "b@x.com", "subject": "s", "text": "t"}
        self.assertEqual(self.anser.emails.send_batch([email], atomic=False), result)
        req = self.stub.requests[0]
        self.assertEqual((req["path"], req["body"]), ("/v1/emails/batch", {"emails": [email], "atomic": False}))
        self.assertTrue(req["headers"]["idempotency-key"].startswith("anser-"))

    def test_walks_every_page(self) -> None:
        pages = {
            None: {"object": "list", "has_more": True, "data": [{"id": "3"}, {"id": "2"}]},
            "2": {"object": "list", "has_more": False, "data": [{"id": "1"}]},
        }

        def answer(req: dict[str, Any]) -> Answer:
            after = req["path"].partition("after=")[2] or None
            return 200, {}, pages[after]

        self.stub.answer = answer
        self.assertEqual([e["id"] for e in self.anser.emails.list_all(limit=2, status="sent")], ["3", "2", "1"])
        self.assertEqual(self.stub.requests[0]["path"], "/v1/emails?limit=2&status=sent")
        page = self.anser.suppressions.list(q="x")
        self.assertTrue(page.has_more)
        self.assertEqual(len(page), 2)

    def test_inbox_filters(self) -> None:
        self.stub.answer = lambda req: (200, {}, {"object": "list", "has_more": False, "data": []})
        self.anser.inbox.list(to=["a@acme.com", "b@acme.com"], from_="amy@x.com", limit=5)
        self.assertEqual(
            self.stub.requests[0]["path"], "/v1/inbox?to=a%40acme.com%2Cb%40acme.com&from=amy%40x.com&limit=5"
        )

    def test_returns_bytes(self) -> None:
        self.stub.answer = lambda req: (200, {"content-type": "application/pdf"}, b"%PDF")
        self.assertEqual(self.anser.emails.attachment("e1", "a1"), b"%PDF")
        self.assertEqual(self.stub.requests[0]["path"], "/v1/emails/e1/attachments/a1")

    def test_times_out_and_fails_to_connect(self) -> None:
        self.stub.answer = lambda req: (time.sleep(0.5), (200, {}, {}))[1]
        with self.assertRaises(AnserConnectionError) as caught:
            Anser("ms_test", base_url=self.stub.url, timeout=0.1, max_retries=0).usage.get()
        self.assertIn("Timed out", str(caught.exception))
        with self.assertRaises(AnserConnectionError):
            Anser("ms_test", base_url="http://127.0.0.1:9", max_retries=0).usage.get()

    def test_needs_a_key(self) -> None:
        saved = os.environ.pop("ANSER_API_KEY", None)
        try:
            with self.assertRaises(ValueError):
                Anser()
        finally:
            if saved is not None:
                os.environ["ANSER_API_KEY"] = saved


class WebhookTest(unittest.TestCase):
    def test_verifies(self) -> None:
        event = verify_webhook(FIXTURE["body"], FIXTURE["headers"], FIXTURE["secret"], now=FIXTURE["now"])
        self.assertEqual(event["type"], "email.delivered")
        self.assertEqual(event["data"]["email"]["subject"], "你好 👋")
        self.assertEqual(event["data"]["email"]["tags"], {"category": "welcome"})
        # bytes, and headers spelled another way
        headers = {k.title(): v for k, v in FIXTURE["headers"].items()}
        verify_webhook(FIXTURE["body"].encode(), headers, FIXTURE["secret"], now=FIXTURE["now"])

    def test_rejects(self) -> None:
        cases = [
            (FIXTURE["body"].replace("你好", "hi"), FIXTURE["headers"], FIXTURE["secret"], FIXTURE["now"]),
            (FIXTURE["body"], FIXTURE["headers"], "whsec_" + base64.b64encode(b"other").decode(), FIXTURE["now"]),
            (FIXTURE["body"], FIXTURE["headers"], FIXTURE["secret"], FIXTURE["now"] + 600),
            (FIXTURE["body"], {"webhook-id": "x"}, FIXTURE["secret"], FIXTURE["now"]),
        ]
        for body, headers, secret, now in cases:
            with self.assertRaises(WebhookVerificationError):
                verify_webhook(body, headers, secret, now=now)


if __name__ == "__main__":
    unittest.main()
