"""知识同步契约单测：两个 schema、record 回流、NO_KB_REQUIRED、query-back。

所有用例都在 tempfile 目录里复制 schema/entries/registry 后运行，
不触碰仓库真实的 entries/ 与 index/。
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import kb  # noqa: E402

SCHEMA = REPO / "schema"
FIXTURES = REPO / "tests" / "fixtures"
SCANNER_HOME = FIXTURES / "fake-skill-git"

TIME = "2026-11-12 10:00:00"
END_TIME = "2026-11-12 10:05:00"
BAD_TIME = "2026-11-12T10:00:00Z"  # noqa: time-lint  # time-lint:allow
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
RUN_ID = "run-20261112-100000-kbsync"
ENTRY_ID = "kb-knowledge-0123456789ab"


def run_kb(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = kb.main([str(item) for item in argv])
    return code, out.getvalue(), err.getvalue()


def make_kb(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "schema").mkdir(exist_ok=True)
    for name in ("entry.v1.json", "receipt.v1.json", "index.v1.json",
                 "kb-context.v1.json", "delivery.v1.json"):
        shutil.copy(SCHEMA / name, root / "schema" / name)
    for entry_type in ("knowledge", "method", "run", "bug"):
        path = root / "entries" / entry_type / "entries.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (root / "index").mkdir(exist_ok=True)
    (root / "registry").mkdir(exist_ok=True)
    shutil.copy(FIXTURES / "registry.skills.json", root / "registry" / "skills.json")
    kb.save_indexes(root, [])
    return root


def row_count(root: Path) -> int:
    total = 0
    for entry_type in kb.ENTRY_TYPES:
        path = kb.entry_file(root, entry_type)
        if path.is_file():
            total += len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    return total


def write_receipt(root: Path, run_id: str = RUN_ID, lessons: list[dict] | None = None) -> Path:
    folder = root / "receipts"
    folder.mkdir(parents=True, exist_ok=True)
    evidence_dir = folder / f"{run_id}.evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "unittest.log"
    log_path.write_text("Ran 3 tests\nOK\n", encoding="utf-8")
    receipt = {
        "schema": "run.receipt.v1",
        "run_id": run_id,
        "task": "知识同步契约自检",
        "skill": "lstest",
        "skill_version": "1.0.0",
        "scope": {"device": "bench-a", "project": "CSK5062", "firmware": "fw-1.0.0", "platform": "linux"},
        "result": "pass",
        "totals": {"rounds": 3, "passed": 3},
        "failures": [],
        "bugs_found": [],
        "evidence_dir": str(evidence_dir),
        "evidence_sha256": [kb.sha256_file(log_path)],
        "lessons": lessons if lessons is not None else [
            {"type": "knowledge", "title": "同步契约串口波特率", "claim": "同步契约自检串口默认 115200", "confidence": "medium"}
        ],
        "confidence": "medium",
        "started_at": TIME,
        "ended_at": END_TIME,
    }
    path = folder / f"{run_id}.run.receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record(root: Path, receipt: Path, *extra: str) -> tuple[int, str, str]:
    return run_kb("record", "--root", root, "--receipt", receipt,
                  "--skill-git-home", SCANNER_HOME, *extra)


def good_context() -> dict:
    return {
        "schema": "ark.kb-context.v1",
        "contract_version": "1.0.0",
        "queried_at": TIME,
        "dims": {
            "capability": ["wake-recognition"],
            "project": "CSK5062",
            "device": None,
            "firmware": None,
            "profile": "default",
            "skill": "lstest",
        },
        "registry_commit": "unknown",
        "hits": [{
            "id": ENTRY_ID,
            "type": "knowledge",
            "status": "active",
            "confidence": "high",
            "score": 7,
            "commit": "unknown",
            "source_skill": "lstest",
        }],
        "no_hit": False,
        "refresh_points": [{"at": "stage:2", "reason": "阶段边界"}],
        "refresh_log": [{"at": TIME, "reason": "registry 变化", "registry_commit": "unknown", "new_hit_ids": []}],
    }


def good_delivery() -> dict:
    return {
        "schema": "ark.delivery.v1",
        "run_id": RUN_ID,
        "idempotency_key": "a" * 64,
        "archive_status": "ok",
        "kb_ingest_status": "recorded",
        "kb_entry_ids": [ENTRY_ID],
        "kb_query_back_status": "pending",
        "retry": {"attempts": 0, "last_error": ""},
        "updated_at": TIME,
    }


class SchemaContractTests(unittest.TestCase):
    def test_kb_context_schema_accepts_good_sample(self) -> None:
        schema = kb.load_schema(REPO, "kb-context.v1.json")
        self.assertEqual(kb.validate(good_context(), schema), [])

    def test_delivery_schema_accepts_good_sample(self) -> None:
        schema = kb.load_schema(REPO, "delivery.v1.json")
        self.assertEqual(kb.validate(good_delivery(), schema), [])
        optional = good_delivery()
        optional.update({
            "archive_manifest_sha256": "b" * 64,
            "kb_query_back_at": TIME,
            "kb_query_back_hits": [ENTRY_ID],
            "no_kb_reason": "duplicate-of-existing:" + ENTRY_ID,
        })
        self.assertEqual(kb.validate(optional, schema), [])

    def test_missing_required_key_rejected(self) -> None:
        context = good_context()
        context.pop("dims")
        errors = kb.validate(context, kb.load_schema(REPO, "kb-context.v1.json"))
        self.assertTrue(any("dims" in item for item in errors), errors)
        delivery = good_delivery()
        delivery.pop("kb_entry_ids")
        errors = kb.validate(delivery, kb.load_schema(REPO, "delivery.v1.json"))
        self.assertTrue(any("kb_entry_ids" in item for item in errors), errors)

    def test_bad_enum_rejected(self) -> None:
        delivery = good_delivery()
        delivery["kb_ingest_status"] = "done"
        errors = kb.validate(delivery, kb.load_schema(REPO, "delivery.v1.json"))
        self.assertTrue(any("允许集合" in item for item in errors), errors)
        context = good_context()
        context["hits"][0]["status"] = "archived"
        errors = kb.validate(context, kb.load_schema(REPO, "kb-context.v1.json"))
        self.assertTrue(any("允许集合" in item for item in errors), errors)

    def test_timezone_designator_timestamp_rejected(self) -> None:
        context = good_context()
        context["queried_at"] = BAD_TIME
        errors = kb.validate(context, kb.load_schema(REPO, "kb-context.v1.json"))
        self.assertTrue(any("queried_at" in item for item in errors), errors)
        delivery = good_delivery()
        delivery["updated_at"] = BAD_TIME
        errors = kb.validate(delivery, kb.load_schema(REPO, "delivery.v1.json"))
        self.assertTrue(any("updated_at" in item for item in errors), errors)


class RecordDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_record_writes_delivery_recorded(self) -> None:
        receipt = write_receipt(self.root)
        delivery_path = self.root / "receipts" / "delivery.json"
        code, out, err = record(self.root, receipt, "--delivery-out", delivery_path)
        self.assertEqual(code, 0, err)
        data = self.load(delivery_path)
        schema = kb.load_schema(self.root, "delivery.v1.json")
        self.assertEqual(kb.validate(data, schema), [])
        self.assertEqual(data["schema"], "ark.delivery.v1")
        self.assertEqual(data["run_id"], RUN_ID)
        self.assertEqual(data["kb_ingest_status"], "recorded")
        self.assertTrue(data["kb_entry_ids"])
        self.assertEqual(data["archive_status"], "pending")
        self.assertEqual(data["kb_query_back_status"], "pending")
        self.assertEqual(data["retry"], {"attempts": 0, "last_error": ""})
        self.assertEqual(len(data["idempotency_key"]), 64)
        self.assertRegex(data["updated_at"], TIME_RE)
        self.assertIn("新增 2 条", out)

    def test_record_replay_does_not_duplicate(self) -> None:
        receipt = write_receipt(self.root)
        delivery_path = self.root / "receipts" / "delivery.json"
        self.assertEqual(record(self.root, receipt, "--delivery-out", delivery_path)[0], 0)
        before = row_count(self.root)
        first_ids = self.load(delivery_path)["kb_entry_ids"]
        code, out, err = record(self.root, receipt, "--delivery-out", delivery_path)
        self.assertEqual(code, 0, err)
        self.assertIn("幂等", out)
        self.assertEqual(row_count(self.root), before)
        data = self.load(delivery_path)
        self.assertEqual(data["kb_ingest_status"], "recorded")
        self.assertEqual(sorted(data["kb_entry_ids"]), sorted(first_ids))

    def test_no_kb_required_skips_entries(self) -> None:
        receipt = write_receipt(self.root)
        delivery_path = self.root / "receipts" / "delivery.json"
        before = row_count(self.root)
        code, out, err = record(self.root, receipt, "--no-kb-required", "--reason",
                                "no-new-knowledge", "--delivery-out", delivery_path)
        self.assertEqual(code, 0, err)
        self.assertIn("跳过入库", out)
        self.assertEqual(row_count(self.root), before)
        data = self.load(delivery_path)
        self.assertEqual(data["kb_ingest_status"], "skipped_no_kb")
        self.assertEqual(data["no_kb_reason"], "no-new-knowledge")
        self.assertEqual(data["kb_entry_ids"], [])
        self.assertEqual(kb.validate(data, kb.load_schema(self.root, "delivery.v1.json")), [])

    def test_no_kb_required_without_reason_is_usage_error(self) -> None:
        receipt = write_receipt(self.root)
        delivery_path = self.root / "receipts" / "delivery.json"
        before = row_count(self.root)
        code, _, err = record(self.root, receipt, "--no-kb-required", "--delivery-out", delivery_path)
        self.assertEqual(code, 2)
        self.assertIn("--reason", err)
        code, _, err = record(self.root, receipt, "--no-kb-required", "--reason", "随便写的",
                              "--delivery-out", delivery_path)
        self.assertEqual(code, 2)
        self.assertEqual(row_count(self.root), before)
        self.assertFalse(delivery_path.exists())

    def test_no_kb_required_accepts_duplicate_reason(self) -> None:
        receipt = write_receipt(self.root)
        delivery_path = self.root / "receipts" / "delivery.json"
        code, _, err = record(self.root, receipt, "--no-kb-required", "--reason",
                              "duplicate-of-existing:" + ENTRY_ID, "--delivery-out", delivery_path)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.load(delivery_path)["no_kb_reason"],
                         "duplicate-of-existing:" + ENTRY_ID)


class QueryBackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)
        self.receipt = write_receipt(self.root)
        self.delivery_path = self.root / "receipts" / "delivery.json"
        code, _, err = record(self.root, self.receipt, "--delivery-out", self.delivery_path)
        self.assertEqual(code, 0, err)

    def load(self) -> dict:
        return json.loads(self.delivery_path.read_text(encoding="utf-8"))

    def test_query_back_passes_and_writes_status(self) -> None:
        ids = self.load()["kb_entry_ids"]
        before = row_count(self.root)
        code, out, err = run_kb("query-back", "--root", self.root, "--delivery", self.delivery_path)
        self.assertEqual(code, 0, err)
        self.assertIn("pass", out)
        data = self.load()
        self.assertEqual(data["kb_query_back_status"], "pass")
        self.assertRegex(data["kb_query_back_at"], TIME_RE)
        self.assertTrue(set(ids).issubset(set(data["kb_query_back_hits"])))
        self.assertEqual(data["kb_ingest_status"], "recorded")
        self.assertEqual(row_count(self.root), before)

    def test_query_back_is_idempotent(self) -> None:
        first = run_kb("query-back", "--root", self.root, "--delivery", self.delivery_path)[0]
        second = run_kb("query-back", "--root", self.root, "--delivery", self.delivery_path)[0]
        self.assertEqual((first, second), (0, 0))
        data = self.load()
        self.assertEqual(data["kb_query_back_status"], "pass")
        self.assertEqual([entry["hits"] for entry in kb.load_entries(self.root)], [0, 0])

    def test_query_back_bogus_id_fails(self) -> None:
        before = row_count(self.root)
        code, out, err = run_kb("query-back", "--root", self.root, "--delivery", self.delivery_path,
                                "--entry-id", "kb-knowledge-ffffffffffff")
        self.assertEqual(code, 1, err)
        self.assertIn("fail", out)
        data = self.load()
        self.assertEqual(data["kb_query_back_status"], "fail")
        self.assertEqual(data["kb_ingest_status"], "recorded")
        self.assertEqual(data["run_id"], RUN_ID)
        self.assertNotIn("kb-knowledge-ffffffffffff", data["kb_query_back_hits"])
        self.assertEqual(row_count(self.root), before)
        self.assertRegex(data["kb_query_back_at"], TIME_RE)

    def test_query_back_uses_delivery_dims(self) -> None:
        code, out, err = run_kb("query-back", "--root", self.root, "--delivery", self.delivery_path,
                                "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["dims"].get("device"), "bench-a")


class LayeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def test_record_only_reads_formal_receipt(self) -> None:
        receipt = write_receipt(self.root)
        candidates = self.root / "receipts" / "candidates"
        candidates.mkdir(parents=True, exist_ok=True)
        candidate = json.loads(receipt.read_text(encoding="utf-8"))
        candidate["run_id"] = "run-20261112-110000-candidate"
        candidate["lessons"] = [{"type": "knowledge", "title": "候选结论不入库",
                                 "claim": "候选层内容不得进入条目标题", "confidence": "high"}]
        (candidates / "candidate-1.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        gaps = self.root / "receipts" / "evidence-gaps"
        gaps.mkdir(parents=True, exist_ok=True)
        (gaps / "gap-1.json").write_text(
            json.dumps({"title": "证据缺口不入库", "missing": ["sha256"]}, ensure_ascii=False),
            encoding="utf-8")

        code, _, err = record(self.root, receipt)
        self.assertEqual(code, 0, err)
        entries = kb.load_entries(self.root)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry["type"] for entry in entries}, {"run", "knowledge"})
        titles = " ".join(entry["title"] for entry in entries)
        self.assertNotIn("候选结论不入库", titles)
        self.assertNotIn("证据缺口不入库", titles)
        self.assertTrue(all(entry["evidence"] for entry in entries))


if __name__ == "__main__":
    unittest.main()
