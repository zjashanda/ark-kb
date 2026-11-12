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
                 "kb-context.v1.json", "delivery.v1.json", "checkpoint.v1.json"):
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


def good_checkpoint(**overrides) -> dict:
    event = {
        "schema": "ark.checkpoint.v1",
        "checkpoint_id": "0" * 64,
        "issue_id": "NOAH-66",
        "run_id": "run-20261112-100000-kbsync",
        "stage": 15,
        "event_seq": 3,
        "trigger": "STAGE_FINISHED",
        "at": TIME,
        "quality": "formal",
        "scope": {"level": "capability", "key": "flashing", "parent": "global"},
        "summary": {
            "title": "烧录超时定位",
            "claim": "供电不足导致烧录超时",
            "phenomenon": "反复重试后仍在 8 秒超时",
            "attempts": ["换 USB 线", "降速到 115200"],
            "excluded": ["驱动版本"],
            "recovery_hint": "先量 VBUS 再重烧",
            "stop_rule": "三次超时后停机",
        },
        "evidence": [{"path": "result/burn.log", "sha256": "a" * 64, "bytes": 128}],
        "outbox": {
            "archive_status": "pending",
            "kb_ingest_status": "pending",
            "kb_query_back_status": "pending",
            "kb_entry_ids": [],
            "retry": {"attempts": 0, "last_error": ""},
        },
    }
    event.update(overrides)
    event["checkpoint_id"] = kb.checkpoint_id(event)
    return event


def write_event(root: Path, name: str, event: dict) -> Path:
    folder = root / "receipts" / "events"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def checkpoint(root: Path, event_path: Path, *extra: str) -> tuple[int, str, str]:
    return run_kb("checkpoint", "--root", root, "--outbox", "receipts/outbox",
                  "--event", event_path, *extra)


def outbox_index(root: Path) -> dict:
    return json.loads((root / "receipts" / "outbox" / "outbox.json").read_text(encoding="utf-8"))


def wal_path(root: Path) -> Path:
    return root / "receipts" / "outbox" / "checkpoints-20261112.jsonl"


def wal_lines(root: Path) -> list[str]:
    path = wal_path(root)
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_entries(root: Path, rows: list[dict]) -> None:
    for entry_type in kb.ENTRY_TYPES:
        path = kb.entry_file(root, entry_type)
        selected = [row for row in rows if row["type"] == entry_type]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected),
                        encoding="utf-8")


def base_entry(entry_id: str, **overrides) -> dict:
    row = {
        "schema": "entry.v1",
        "id": entry_id,
        "type": "knowledge",
        "scope": {"device": None, "project": None, "firmware": None, "platform": None},
        "title": "标题",
        "claim": "结论",
        "evidence": [{"kind": "issue", "ref": "NOAH-66"}],
        "confidence": "medium",
        "status": "active",
        "superseded_by": None,
        "source_skill": None,
        "created": TIME,
        "updated": TIME,
        "hits": 0,
        "validations": ["run-20261112-100000-kbsync"],
    }
    row.update(overrides)
    return row


class CheckpointSchemaTests(unittest.TestCase):
    def load(self) -> dict:
        return kb.load_schema(REPO, "checkpoint.v1.json")

    def test_good_event_accepted(self) -> None:
        self.assertEqual(kb.validate(good_checkpoint(), self.load()), [])

    def test_bad_trigger_rejected(self) -> None:
        event = good_checkpoint()
        event["trigger"] = "TASK_DONE"
        errors = kb.validate(event, self.load())
        self.assertTrue(any("允许集合" in item for item in errors), errors)

    def test_bad_checkpoint_id_rejected(self) -> None:
        event = good_checkpoint()
        event["checkpoint_id"] = "not-a-sha256"
        errors = kb.validate(event, self.load())
        self.assertTrue(any("checkpoint_id" in item for item in errors), errors)

    def test_bad_timestamp_rejected(self) -> None:
        event = good_checkpoint()
        event["at"] = BAD_TIME
        errors = kb.validate(event, self.load())
        self.assertTrue(any("$.at" in item for item in errors), errors)

    def test_missing_outbox_field_rejected(self) -> None:
        event = good_checkpoint()
        event["outbox"].pop("kb_entry_ids")
        errors = kb.validate(event, self.load())
        self.assertTrue(any("kb_entry_ids" in item for item in errors), errors)

    def test_entry_schema_accepts_scope_extensions(self) -> None:
        row = base_entry(
            "kb-knowledge-bbbbbbbbbbbb",
            scope_level="project",
            scope_key="TCL",
            parent_scope="capability:flashing",
            derived_from=["kb-knowledge-0123456789ab"],
            applies_to=["TCL", "CSK5062"],
            exceptions=[{"rule": "烧录前断电", "reason": "上电烧录会锁死"}],
            promote_to="capability",
            lineage=["kb-knowledge-0123456789ab"],
            checkpoint_ids=["c" * 64],
        )
        self.assertEqual(kb.validate(row, kb.load_schema(REPO, "entry.v1.json")), [])


class CheckpointWalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def test_append_once_and_replay_is_idempotent(self) -> None:
        event = good_checkpoint()
        path = write_event(self.root, "stage-15.json", event)
        code, out, err = checkpoint(self.root, path)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(wal_lines(self.root)), 1)
        index = outbox_index(self.root)
        self.assertIn(event["checkpoint_id"], index)
        self.assertEqual(index[event["checkpoint_id"]]["trigger"], "STAGE_FINISHED")
        self.assertEqual(index[event["checkpoint_id"]]["stage"], 15)

        code, out, err = checkpoint(self.root, path)
        self.assertEqual(code, 0, err)
        self.assertIn("duplicate checkpoint", out)
        self.assertEqual(len(wal_lines(self.root)), 1)

    def test_schema_error_exits_two_without_writing(self) -> None:
        event = good_checkpoint()
        event["trigger"] = "TASK_DONE"
        path = write_event(self.root, "bad.json", event)
        code, _, err = checkpoint(self.root, path)
        self.assertEqual(code, 2)
        self.assertIn("拒绝写入 WAL", err)
        self.assertEqual(wal_lines(self.root), [])
        self.assertFalse((self.root / "receipts" / "outbox" / "outbox.json").exists())

    def test_outbox_replay_restores_missing_index_line(self) -> None:
        event = good_checkpoint()
        path = write_event(self.root, "stage-15.json", event)
        self.assertEqual(checkpoint(self.root, path)[0], 0)
        wal_before = wal_path(self.root).read_bytes()
        index = outbox_index(self.root)
        index.pop(event["checkpoint_id"])
        (self.root / "receipts" / "outbox" / "outbox.json").write_text(
            json.dumps(index), encoding="utf-8")

        code, out, err = run_kb("outbox", "--root", self.root, "--replay", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["replayed"], 1)
        self.assertIn(event["checkpoint_id"], outbox_index(self.root))
        self.assertEqual(wal_path(self.root).read_bytes(), wal_before)

    def test_outbox_status_filter_and_pending_counts(self) -> None:
        event = good_checkpoint()
        path = write_event(self.root, "stage-15.json", event)
        self.assertEqual(checkpoint(self.root, path)[0], 0)
        payload = json.loads(run_kb("outbox", "--root", self.root, "--json")[1])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["pending"], 1)
        payload = json.loads(run_kb("outbox", "--root", self.root,
                                    "--status", "archived", "--json")[1])
        self.assertEqual(payload["items"], [])


class RecordCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)
        self.receipt = write_receipt(self.root)
        self.event = good_checkpoint()
        path = write_event(self.root, "stage-15.json", self.event)
        self.assertEqual(checkpoint(self.root, path)[0], 0)

    def test_record_stamps_checkpoint_ids(self) -> None:
        cid = self.event["checkpoint_id"]
        code, _, err = record(self.root, self.receipt, "--checkpoint", cid)
        self.assertEqual(code, 0, err)
        entries = kb.load_entries(self.root)
        self.assertTrue(entries)
        for entry in entries:
            self.assertIn(cid, entry.get("checkpoint_ids") or [])
        schema = kb.load_schema(self.root, "entry.v1.json")
        for entry in entries:
            self.assertEqual(kb.validate(entry, schema), [])

    def test_unknown_checkpoint_refused_without_writing(self) -> None:
        before = row_count(self.root)
        code, _, err = record(self.root, self.receipt, "--checkpoint", "f" * 64)
        self.assertEqual(code, 2)
        self.assertIn("未知 checkpoint", err)
        self.assertEqual(row_count(self.root), before)


class PromoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def seed(self) -> None:
        write_entries(self.root, [
            base_entry("kb-knowledge-cccccccccccc", title="烧录前必须断电",
                       claim="所有板型烧录前断电可避免锁死",
                       applies_to=["CSK5062", "TCL"],
                       tags=["capability:burn"]),
            base_entry("kb-knowledge-dddddddddddd", title="单项目结论",
                       claim="只在 TCL 上验证过",
                       applies_to=["TCL"]),
        ])

    def test_candidate_found_and_nothing_written(self) -> None:
        self.seed()
        before = sorted(path.relative_to(self.root).as_posix()
                        for path in self.root.rglob("*") if path.is_file())
        code, out, err = run_kb("promote", "--root", self.root, "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        ids = [row["entry_id"] for row in payload["candidates"]]
        self.assertEqual(ids, ["kb-knowledge-cccccccccccc"])
        row = payload["candidates"][0]
        self.assertEqual(row["promote_to"], "capability")
        self.assertEqual(row["projects"], ["CSK5062", "TCL"])
        self.assertIn("reason", row)
        after = sorted(path.relative_to(self.root).as_posix()
                       for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(before, after)

    def test_out_writes_report(self) -> None:
        self.seed()
        code, _, err = run_kb("promote", "--root", self.root,
                              "--out", "reports/promote.json", "--json")
        self.assertEqual(code, 0, err)
        report_path = self.root / "reports" / "promote.json"
        self.assertTrue(report_path.is_file())
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["candidates"]), 1)


class CrossProjectScopeTests(unittest.TestCase):
    CAPABILITY = "kb-knowledge-111111111111"
    PROJECT_A = "kb-knowledge-222222222222"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)
        write_entries(self.root, [
            base_entry(self.CAPABILITY, title="烧录超时先量供电",
                       claim="供电不足是烧录超时最常见原因",
                       scope_level="capability", scope_key="flashing", parent_scope="global",
                       tags=["capability:flashing"],
                       applies_to=["CSK5062", "TCL"]),
            base_entry(self.PROJECT_A, title="TCL 烧录必须断电",
                       claim="TCL 板上电烧录会锁死",
                       scope={"device": None, "project": "TCL", "firmware": None, "platform": None},
                       scope_level="project", scope_key="TCL",
                       parent_scope="capability:flashing",
                       derived_from=[self.CAPABILITY],
                       exceptions=[{"rule": "烧录前断电", "reason": "TCL 硬件版本差异"}],
                       tags=["capability:flashing"]),
        ])

    def query_ids(self, project: str) -> list[str]:
        code, out, err = run_kb("query", "--root", self.root, "--project", project,
                                "--capability", "flashing", "--json", "--no-hit-count")
        self.assertEqual(code, 0, err)
        return [item["id"] for item in json.loads(out)["entries"]]

    def test_other_project_hits_capability_not_exception(self) -> None:
        ids = self.query_ids("CSK5062")
        self.assertIn(self.CAPABILITY, ids)
        self.assertNotIn(self.PROJECT_A, ids)

    def test_exception_still_applies_to_its_own_project(self) -> None:
        ids = self.query_ids("TCL")
        self.assertIn(self.PROJECT_A, ids)
        self.assertIn(self.CAPABILITY, ids)


if __name__ == "__main__":
    unittest.main()
