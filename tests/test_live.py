"""Against a running server; skipped unless ANSER_LIVE_BASE_URL, ANSER_LIVE_API_KEY and ANSER_LIVE_FROM are set.

ANSER_LIVE_FROM is an address on a verified domain of that workspace. Mail goes to the SES simulator
(success@simulator.amazonses.com), which does not count towards the quota.
"""

from __future__ import annotations

import datetime
import os
import unittest
import uuid

from anser_mail import Anser, AnserError
from anser_mail.types import SendEmailParams

LIVE = {name: os.environ.get(f"ANSER_LIVE_{name}", "") for name in ("BASE_URL", "API_KEY", "FROM")}
TO = "success@simulator.amazonses.com"


@unittest.skipUnless(all(LIVE.values()), "set ANSER_LIVE_BASE_URL, ANSER_LIVE_API_KEY and ANSER_LIVE_FROM")
class LiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.anser = Anser(LIVE["API_KEY"], base_url=LIVE["BASE_URL"])

    def test_schedules_reads_moves_and_cancels(self) -> None:
        at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) + datetime.timedelta(days=1)
        params: SendEmailParams = {
            "from": LIVE["FROM"],
            "to": TO,
            "subject": "SDK 联调 👋",
            "text": "python",
            "attachments": [{"filename": "hi.txt", "content": "你好".encode()}],
            "tags": {"sdk": "python"},
            "scheduled_at": at,
        }
        key = f"live-{uuid.uuid4()}"
        sent = self.anser.emails.send(params, idempotency_key=key)
        # the same key answers with the same email
        self.assertEqual(self.anser.emails.send(params, idempotency_key=key), sent)

        email = self.anser.emails.get(sent["id"])
        self.assertEqual((email["status"], email["to"], email["subject"]), ("scheduled", [TO], "SDK 联调 👋"))
        self.assertEqual(email["tags"], {"sdk": "python"})
        attachment = email["attachments"][0]
        self.assertEqual(self.anser.emails.attachment(sent["id"], attachment["id"]), "你好".encode())

        moved = self.anser.emails.update(sent["id"], scheduled_at=at + datetime.timedelta(hours=1))
        self.assertEqual(moved["status"], "scheduled")
        self.assertEqual(self.anser.emails.cancel(sent["id"])["status"], "canceled")
        types = [e["type"] for e in self.anser.emails.events(sent["id"])]
        self.assertEqual(types, ["email.scheduled", "email.scheduled", "email.canceled"])
        self.assertIn(sent["id"], [e["id"] for e in self.anser.emails.list(limit=5)])

    def test_sends_a_batch(self) -> None:
        batch = self.anser.emails.send_batch(
            [{"from": LIVE["FROM"], "to": TO, "subject": f"SDK 联调 {n}", "text": "python"} for n in (1, 2)]
        )
        self.assertEqual([e["subject"] for e in batch["data"] if e], ["SDK 联调 1", "SDK 联调 2"])

        partial = self.anser.emails.send_batch(
            [
                {"from": LIVE["FROM"], "to": TO, "subject": "SDK 联调 3", "text": "python"},
                {"from": LIVE["FROM"], "to": "nope", "subject": "SDK 联调 4", "text": "python"},
            ],
            atomic=False,
        )
        self.assertIsNone(partial["data"][1])
        self.assertEqual(partial["errors"][0]["param"], "emails[1].to[0]")

    def test_the_rest_of_the_workspace(self) -> None:
        domain = LIVE["FROM"].rsplit("@", 1)[1].rstrip(">")
        self.assertIn(domain, [d["name"] for d in self.anser.domains.list()])
        self.assertEqual(self.anser.usage.get()["object"], "usage")
        self.assertIn("sent", self.anser.stats.get(days=7)["totals"])
        address = f"sdk-live-{uuid.uuid4().hex[:8]}@example.com"
        self.assertEqual(self.anser.suppressions.add(address)["address"], address)
        self.anser.suppressions.remove(address)
        self.assertNotIn(address, [s["address"] for s in self.anser.suppressions.list(q=address)])
        with self.assertRaises(AnserError) as caught:
            self.anser.emails.get("01938a1c-0000-7000-8000-000000000000")
        self.assertEqual((caught.exception.status_code, caught.exception.code), (404, "not_found"))
