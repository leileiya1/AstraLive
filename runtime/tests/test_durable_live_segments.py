import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest
from app.durable_live_segments import SegmentRejected, exact_script_text


class ExactScriptTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.text = "价格129.90元，尺码XL/XXL/2XL。"
        self.fact = dict(kind="PRICE", productId="product", sourceVersion="v1",
                         valueHash=sha256(b"129.90").hexdigest(),
                         validatedAt="2026-10-16T00:00:00Z", expiresAt="2026-10-16T00:00:02Z")
        self.payload = dict(mode="SCRIPT_TEXT", productId="product", planId="plan",
                            segmentId="segment", text=self.text,
                            textHash=sha256(self.text.encode()).hexdigest(),
                            expiresAt="2026-10-16T00:00:20Z", factDependencies=[self.fact])

    def exact(self, payload=None, **kw):
        return exact_script_text(payload or self.payload, product_id="product",
                                 source_version="v1", validated_facts=kw.pop("facts", [self.fact]),
                                 now=kw.pop("now", self.now), **kw)

    def test_exact_text_is_not_rewritten(self):
        self.assertEqual(self.exact(), self.text)
        self.assertEqual(self.payload["text"], self.text)

    def test_wrong_product_hash_mode_and_deadline(self):
        for key, value in [("productId", "other"), ("textHash", "bad"),
                           ("mode", "COMMENT_QUESTION"), ("expiresAt", "2026-10-16T00:00:00Z")]:
            with self.subTest(key=key), self.assertRaises(SegmentRejected):
                payload = copy.deepcopy(self.payload); payload[key] = value; self.exact(payload)

    def test_expiry_future_clock_and_unsupported_fact(self):
        for key, value in [("validatedAt", "2026-10-16T00:00:01Z"),
                           ("expiresAt", "2026-10-16T00:00:03Z"), ("kind", "SKU_STOCK"),
                           ("productId", "other"), ("sourceVersion", "v2"), ("valueHash", "bad")]:
            with self.subTest(key=key), self.assertRaises(SegmentRejected):
                fact = copy.deepcopy(self.fact); fact[key] = value; self.exact(facts=[fact])
        with self.assertRaises(SegmentRejected):
            self.exact(now=self.now + timedelta(seconds=2))

    def test_changed_value_cannot_become_fresh(self):
        fact = copy.deepcopy(self.fact); fact["valueHash"] = sha256(b"199.90").hexdigest()
        with self.assertRaises(SegmentRejected): self.exact(facts=[fact])

    def test_empty_facts_and_exact_unicode_preservation(self):
        payload = copy.deepcopy(self.payload); payload["factDependencies"] = []
        for text in ["型号AB-2XL-Pro。", "容量500 mL。", "不是混纺，而是纯棉。", "e\u0301。"]:
            payload["text"] = text; payload["textHash"] = sha256(text.encode()).hexdigest()
            self.assertEqual(self.exact(payload, facts=[]), text)

    def test_cancelled_or_failed_execution_has_no_completion_side_effect(self):
        # The helper only returns frozen text. It has no API that could declare
        # completion, acquire another generation or enqueue media on failure.
        before = copy.deepcopy(self.payload)
        with self.assertRaises(SegmentRejected): self.exact(facts=[])
        self.assertEqual(before, self.payload)


if __name__ == "__main__": unittest.main()
