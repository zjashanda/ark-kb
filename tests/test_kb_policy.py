"""kb_policy 单测：判定矩阵、前置检查快照。离线，不访问网络。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import kb_policy  # noqa: E402

CACHE_OK = {
    "entry_ids": ["kb-method-aaaaaaaaaaa1"],
    "source_commit": "abc1234",
    "recorded_at": "2026-11-16 18:00:00",
    "age_seconds": 60,
    "max_age_seconds": 3600,
}
CACHE_OLD = dict(CACHE_OK, recorded_at="2026-11-01 00:00:00", age_seconds=10 ** 6)


class EvaluateMatrixTests(unittest.TestCase):
    def test_fresh_proceeds_for_both_risks(self):
        for risk in ("normal", "high"):
            decision = kb_policy.evaluate(risk=risk, freshness="fresh")
            self.assertEqual(decision["decision"], "PROCEED")
            self.assertIn("knowledge_snapshot", decision["receipt_required"])

    def test_stale_blocks_high_risk_only(self):
        high = kb_policy.evaluate(risk="high", freshness="stale", cache=CACHE_OK)
        self.assertEqual(high["decision"], "BLOCKED_KB_STALE")
        normal = kb_policy.evaluate(risk="normal", freshness="stale", cache=CACHE_OK)
        self.assertEqual(normal["decision"], "PROCEED_WITH_CACHE")
        self.assertIn("freshness=stale", normal["receipt_required"])

    def test_stale_with_expired_cache_falls_back_to_git(self):
        decision = kb_policy.evaluate(risk="normal", freshness="stale", cache=CACHE_OLD)
        self.assertEqual(decision["decision"], "GIT_FALLBACK")

    def test_unavailable_blocks_high_risk(self):
        decision = kb_policy.evaluate(risk="high", freshness="unavailable", cache=CACHE_OK)
        self.assertEqual(decision["decision"], "BLOCKED_KB_UNAVAILABLE")

    def test_unavailable_normal_uses_cache_then_git(self):
        cached = kb_policy.evaluate(risk="normal", freshness="unavailable", cache=CACHE_OK)
        self.assertEqual(cached["decision"], "PROCEED_WITH_CACHE")
        self.assertIn("kb_unavailable=true", cached["receipt_required"])
        none = kb_policy.evaluate(risk="normal", freshness="unavailable")
        self.assertEqual(none["decision"], "GIT_FALLBACK")

    def test_unknown_is_treated_as_unavailable(self):
        high = kb_policy.evaluate(risk="high", freshness="unknown", cache=CACHE_OK)
        self.assertEqual(high["decision"], "BLOCKED_KB_UNAVAILABLE")
        normal = kb_policy.evaluate(risk="normal", freshness="unknown", cache=CACHE_OLD)
        self.assertEqual(normal["decision"], "GIT_FALLBACK")

    def test_invalid_arguments_rejected(self):
        with self.assertRaises(ValueError):
            kb_policy.evaluate(risk="impossible", freshness="fresh")
        with self.assertRaises(ValueError):
            kb_policy.evaluate(risk="normal", freshness="maybe")


class PreflightTests(unittest.TestCase):
    def test_preflight_carries_snapshot_and_checks(self):
        entries = [{
            "id": "kb-method-aaaaaaaaaaa1",
            "status": "active",
            "title": "证据入库只登记路径与 SHA-256",
            "claim": "只登记 evidence_ref，原始文件留在存储服务",
            "evidence": [{"kind": "file", "ref": "ark://evidence/x/receipt.json"}],
        }]
        preflight = kb_policy.build_preflight(
            task="同类任务", freshness="fresh", source_commit="abc1234",
            indexed_commit="abc1234", entries=entries, recorded_at="2026-11-16 18:00:00")
        self.assertEqual(preflight["schema"], "ark.knowledge-preflight.v1")
        snapshot = preflight["knowledge_snapshot"]
        self.assertEqual(snapshot["entry_ids"], ["kb-method-aaaaaaaaaaa1"])
        self.assertEqual(preflight["checks"][0]["must_read"], entries[0]["claim"])
        markdown = kb_policy.render_markdown(preflight)
        self.assertIn("kb-method-aaaaaaaaaaa1", markdown)
        self.assertIn("source_commit=abc1234", markdown)

    def test_preflight_allows_empty_hits(self):
        preflight = kb_policy.build_preflight(
            task="同类任务", freshness="fresh", source_commit="abc", indexed_commit="abc",
            entries=[], recorded_at="2026-11-16 18:00:00")
        self.assertEqual(preflight["knowledge_snapshot"]["entry_ids"], [])
        self.assertIn("无", kb_policy.render_markdown(preflight))


if __name__ == "__main__":
    unittest.main()
