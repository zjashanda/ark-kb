"""能力标签与查询别名：保证 `--capability wake-recognition` 与「唤醒」都能命中。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import kb  # noqa: E402


class CapabilityTagsTest(unittest.TestCase):
    def test_aliases_both_directions(self):
        self.assertIn("唤醒", kb.expand_capability("wake-recognition"))
        self.assertIn(kb.norm_text("wake-recognition"), kb.expand_capability("唤醒"))
        self.assertIn("crash", kb.expand_capability("崩溃"))

    def test_derived_slugs_from_text(self):
        slugs = kb.capability_slugs("唤醒 + 命令词识别长稳压测", "崩溃后重启", "看门狗判定")
        for expected in ("wake-recognition", "crash", "watchdog"):
            self.assertIn(expected, slugs)

    def test_receipt_without_tags_still_hits(self):
        """回执没有 tags 字段时，record 也要补能力标签，否则入库后查不到。"""
        slugs = kb.capability_slugs("TCL 离线语音交互压测：唤醒 + 命令词识别长稳")
        self.assertTrue(slugs)
        tags = [f"capability:{slug}" for slug in slugs]
        entry = kb.new_entry("run", {"device": "CSK7", "project": "tcl"}, "t", "c", [],
                             "medium", "tcl-test-sub", "run-1", tags=tags)
        keys = kb.capability_keys(entry, None, include_registry=False)
        self.assertIn(kb.norm_text("capability:wake-recognition"), keys)

    def test_query_score_matches_chinese(self):
        entry = kb.new_entry("run", {"device": "CSK7"}, "t", "c", [], "medium",
                             "tcl-test-sub", "run-1", tags=["capability:wake-recognition"])
        score = kb.query_score(entry, {"device": "CSK7", "capability": "唤醒"}, None)
        self.assertIsNotNone(score)


if __name__ == "__main__":
    unittest.main()
