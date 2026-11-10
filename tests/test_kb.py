"""ark-kb 单测：离线、不访问网络（sync 用本地 bare 仓库）。"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import kb  # noqa: E402
import secret_scan  # noqa: E402

SCHEMA = REPO / "schema"
FIXTURES = REPO / "tests" / "fixtures"
SCANNER_HOME = FIXTURES / "fake-skill-git"
FAKE_SKILL = "lstest"


def run_kb(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = kb.main([str(item) for item in argv])
    return code, out.getvalue(), err.getvalue()


def make_kb(root: Path, with_registry: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "schema").mkdir(exist_ok=True)
    for name in ("entry.v1.json", "receipt.v1.json", "index.v1.json"):
        shutil.copy(SCHEMA / name, root / "schema" / name)
    (root / "entries").mkdir(exist_ok=True)
    (root / "index").mkdir(exist_ok=True)
    if with_registry:
        (root / "registry").mkdir(exist_ok=True)
        shutil.copy(FIXTURES / "registry.skills.json", root / "registry" / "skills.json")
    kb.save_indexes(root, [])
    return root


def write_receipt(
    root: Path,
    run_id: str = "run-20261106T100000Z-demo",
    *,
    device: str | None = "bench-a",
    project: str | None = "CSK5062-xiaodu-fan",
    firmware: str | None = "fw-1.0.0",
    skill: str = FAKE_SKILL,
    result: str = "pass",
    lessons: list[dict] | None = None,
    bugs: list[dict] | None = None,
    evidence: dict[str, str] | None = None,
    override: dict | None = None,
    evidence_dir: str | None = None,
) -> Path:
    folder = root / "docs" / "receipts"
    folder.mkdir(parents=True, exist_ok=True)
    evidence_name = f"{run_id}.evidence"
    evidence_path = folder / evidence_name
    evidence_path.mkdir(parents=True, exist_ok=True)
    payload = evidence if evidence is not None else {"unittest.log": "Ran 3 tests\nOK\n"}
    hashes = []
    for name, content in payload.items():
        path = evidence_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        hashes.append(kb.sha256_file(path))
    receipt = {
        "schema": "run.receipt.v1",
        "run_id": run_id,
        "task": f"演示任务 {run_id}",
        "skill": skill,
        "skill_version": "1.0.0",
        "scope": {"device": device, "project": project, "firmware": firmware, "platform": "linux"},
        "result": result,
        "totals": {"rounds": 5, "passed": 5, "failed": 0},
        "failures": [],
        "bugs_found": bugs or [],
        "evidence_dir": evidence_dir if evidence_dir is not None else evidence_name,
        "evidence_sha256": hashes,
        "lessons": lessons or [],
        "confidence": "medium",
        "started_at": "2026-11-06T10:00:00Z",
        "ended_at": "2026-11-06T10:05:00Z",
    }
    if override:
        receipt.update(override)
    path = folder / f"{run_id}.run.receipt.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record(root: Path, receipt: Path, *extra: str, scanner: bool = True) -> tuple[int, str, str]:
    argv = ["record", "--root", root, "--receipt", receipt]
    if scanner:
        argv += ["--skill-git-home", SCANNER_HOME]
    return run_kb(*argv, *extra)


def lesson(title: str = "串口默认波特率", claim: str = "CSK 台架的日志串口默认 115200 8N1") -> dict:
    return {"type": "knowledge", "title": title, "claim": claim, "confidence": "medium"}


class KBTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def entries(self) -> list[dict]:
        return kb.load_entries(self.root)


class RecordTests(KBTestBase):
    def test_record_creates_pending_entries_and_index(self) -> None:
        receipt = write_receipt(
            self.root,
            lessons=[lesson()],
            bugs=[{"title": "唤醒失败", "claim": "第 3 轮唤醒无响应", "severity": "major"}],
        )
        code, out, err = record(self.root, receipt)
        self.assertEqual(code, 0, err)
        entries = self.entries()
        self.assertEqual({entry["type"] for entry in entries}, {"run", "knowledge", "bug"})
        self.assertTrue(all(entry["status"] == "pending" for entry in entries))
        self.assertTrue(all(entry["evidence"] for entry in entries))
        by_skill = json.loads((self.root / "index" / "by-skill.json").read_text(encoding="utf-8"))
        self.assertIn(FAKE_SKILL, by_skill["keys"])
        by_device = json.loads((self.root / "index" / "by-device.json").read_text(encoding="utf-8"))
        self.assertIn("bencha", json.dumps(by_device["keys"], ensure_ascii=False))

    def test_record_is_idempotent(self) -> None:
        receipt = write_receipt(self.root, lessons=[lesson()])
        self.assertEqual(record(self.root, receipt)[0], 0)
        code, out, _ = record(self.root, receipt)
        self.assertEqual(code, 0)
        self.assertIn("已入库", out)
        self.assertEqual(len(self.entries()), 2)

    def test_record_rejects_missing_evidence(self) -> None:
        receipt = write_receipt(self.root, override={"evidence_dir": "", "evidence_sha256": []})
        code, _, err = record(self.root, receipt)
        self.assertEqual(code, 3)
        self.assertIn("evidence_dir", err)
        self.assertEqual(self.entries(), [])

    def test_record_rejects_hash_mismatch(self) -> None:
        receipt = write_receipt(self.root)
        data = json.loads(receipt.read_text(encoding="utf-8"))
        data["evidence_sha256"] = ["0" * 64]
        receipt.write_text(json.dumps(data), encoding="utf-8")
        code, _, err = record(self.root, receipt)
        self.assertEqual(code, 3)
        self.assertIn("不匹配", err)

    def test_record_rejects_secret_in_receipt(self) -> None:
        receipt = write_receipt(
            self.root,
            lessons=[lesson(claim="把 FAKE_SECRET_ABCDEF12 写进了配置")],
        )
        code, _, err = record(self.root, receipt)
        self.assertEqual(code, 3)
        self.assertIn("凭据规则", err)
        self.assertNotIn("FAKE_SECRET_ABCDEF12", err)

    def test_scanner_fail_closed(self) -> None:
        receipt = write_receipt(self.root)
        with mock.patch.object(secret_scan, "DEFAULT_HOMES", ()):
            with mock.patch.dict("os.environ", {"SKILL_GIT_HOME": ""}, clear=False):
                code, _, err = record(self.root, receipt, scanner=False)
                self.assertEqual(code, 3)
                self.assertIn("找不到 skill-git 扫描器", err)
                code, _, _ = record(self.root, receipt, "--allow-missing-scanner", scanner=False)
                self.assertEqual(code, 0)

    def test_record_propagates_capability_tags(self) -> None:
        """回执自带的 tags 必须落到条目上，否则 --capability 英文能力名永远查不到。"""
        receipt = write_receipt(
            self.root,
            "run-20261107T100000Z-tagged",
            device="CSK7",
            project="TCL",
            lessons=[lesson(title="algo.restart 可恢复", claim="停摆后 0.2 秒恢复")],
            bugs=[{"title": "1-3 分钟必崩", "claim": "exception:8000000c", "tags": ["crash"]}],
            override={"tags": ["wake-recognition", "wake-recognition", " "]},
        )
        self.assertEqual(record(self.root, receipt)[0], 0)
        entries = self.entries()
        self.assertTrue(all(entry.get("tags") for entry in entries))
        for entry in entries:
            self.assertIn("wake-recognition", entry["tags"])
        bug = next(entry for entry in entries if entry["type"] == "bug")
        self.assertEqual(bug["tags"], ["crash", "wake-recognition"])
        code, out, err = run_kb(
            "query", "--root", self.root, "--device", "CSK7",
            "--capability", "wake-recognition", "--json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertGreaterEqual(payload["returned"], 3)
        by_capability = json.loads((self.root / "index" / "by-capability.json").read_text(encoding="utf-8"))
        self.assertIn("wakerecognition", by_capability["keys"])

    def test_merge_promotes_after_second_independent_run(self) -> None:
        first = write_receipt(self.root, "run-20261106T100000Z-a", lessons=[lesson()])
        second = write_receipt(self.root, "run-20261106T110000Z-b", lessons=[lesson()])
        self.assertEqual(record(self.root, first)[0], 0)
        self.assertEqual(record(self.root, second)[0], 0)
        knowledge = [entry for entry in self.entries() if entry["type"] == "knowledge"]
        self.assertEqual(len(knowledge), 1)
        self.assertEqual(knowledge[0]["status"], "active")
        self.assertEqual(len(knowledge[0]["validations"]), 2)
        self.assertGreaterEqual(len(knowledge[0]["evidence"]), 2)

    def test_supersede_keeps_old_entry(self) -> None:
        first = write_receipt(self.root, "run-20261106T100000Z-a", lessons=[lesson(claim="默认 9600")])
        second = write_receipt(self.root, "run-20261106T110000Z-b", lessons=[lesson(claim="实测 115200")])
        self.assertEqual(record(self.root, first)[0], 0)
        old = next(entry for entry in self.entries() if entry["type"] == "knowledge")
        code, _, err = record(self.root, second, "--supersede", old["id"])
        self.assertEqual(code, 0, err)
        entries = {entry["id"]: entry for entry in self.entries()}
        self.assertEqual(entries[old["id"]]["status"], "superseded")
        new_id = entries[old["id"]]["superseded_by"]
        self.assertIn(new_id, entries)
        self.assertEqual(entries[new_id]["status"], "pending")
        code, _, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 0)


class ReceiptEvidenceTests(KBTestBase):
    """evidence_dir 不在本机时，证据仍要保住远端真实存储路径。"""

    def remote_dir(self) -> str:
        return str(self.tmp / "remote" / "results" / "win009" / "tcl-r5" / "20261102_090644_wake_recognition")

    def run_entry(self) -> dict:
        return next(entry for entry in self.entries() if entry["type"] == "run")

    def rewrite(self, receipt: Path, **fields) -> Path:
        data = json.loads(receipt.read_text(encoding="utf-8"))
        data.update(fields)
        receipt.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return receipt

    def test_non_local_evidence_files_keep_storage_paths(self) -> None:
        names = ["wake.log", "uart.log"]
        receipt = write_receipt(
            self.root,
            evidence_dir=self.remote_dir(),
            evidence={name: f"{name} 内容\n" for name in names},
        )
        data = json.loads(receipt.read_text(encoding="utf-8"))
        self.rewrite(receipt, evidence_files=[
            {"path": name, "sha256": value} for name, value in zip(names, data["evidence_sha256"])
        ])
        code, out, err = record(self.root, receipt)
        self.assertEqual(code, 0, err)
        self.assertIn("不在本机", out)
        evidence = self.run_entry()["evidence"]
        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(item["kind"] == "file" for item in evidence))
        self.assertTrue(all(item["verified"] is False for item in evidence))
        self.assertEqual([item["ref"] for item in evidence], [f"{self.remote_dir()}/{name}" for name in names])

    def test_non_local_without_evidence_files_stays_run_level(self) -> None:
        receipt = write_receipt(
            self.root,
            "run-20261102T090644Z-remote",
            evidence_dir=self.remote_dir(),
            evidence={"wake.log": "a\n", "uart.log": "b\n"},
        )
        code, out, err = record(self.root, receipt)
        self.assertEqual(code, 0, err)
        self.assertIn("不在本机", out)
        evidence = self.run_entry()["evidence"]
        self.assertEqual({item["kind"] for item in evidence}, {"run"})
        self.assertEqual([item["ref"] for item in evidence], ["run-20261102T090644Z-remote"] * 2)

    def test_invalid_evidence_files_entry_dropped(self) -> None:
        receipt = write_receipt(
            self.root,
            evidence_dir=self.remote_dir(),
            evidence={"wake.log": "a\n", "uart.log": "b\n"},
        )
        data = json.loads(receipt.read_text(encoding="utf-8"))
        valid = data["evidence_sha256"][0]
        self.rewrite(receipt, evidence_files=[
            {"path": "wake.log", "sha256": valid},
            {"path": "uart.log", "sha256": "0" * 63},
        ])
        code, out, err = record(self.root, receipt)
        self.assertEqual(code, 0, err)
        self.assertIn("evidence_files 有 1 项无效或不匹配", out)
        evidence = self.run_entry()["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["ref"], f"{self.remote_dir()}/wake.log")
        self.assertEqual(evidence[0]["sha256"], valid)


class QueryTests(KBTestBase):
    def test_device_query_hits_and_counts_hits(self) -> None:
        first = write_receipt(self.root, "run-20261106T120000Z-a", device="bench-a", lessons=[lesson()])
        second = write_receipt(self.root, "run-20261106T120100Z-b", device="bench-b", lessons=[lesson(title="另一台", claim="另一台设备的现象")])
        self.assertEqual(record(self.root, first)[0], 0)
        self.assertEqual(record(self.root, second)[0], 0)
        code, out, err = run_kb("query", "--root", self.root, "--device", "bench-a", "--top", "5")
        self.assertEqual(code, 0, err)
        self.assertIn("bench-a", out)
        self.assertNotIn("bench-b", out)
        after = {entry["id"]: entry for entry in self.entries()}
        self.assertTrue(any(entry["hits"] == 1 for entry in after.values()))
        run_kb("query", "--root", self.root, "--device", "bench-a", "--top", "5")
        after = {entry["id"]: entry for entry in self.entries()}
        self.assertTrue(any(entry["hits"] == 2 for entry in after.values()))

    def test_capability_query_uses_registry(self) -> None:
        self.assertEqual(record(self.root, write_receipt(self.root, "run-20261106T130000Z-c", skill="cskflashtest", lessons=[lesson(title="烧录", claim="下电 3 秒后进 boot")]))[0], 0)
        code, out, _ = run_kb("query", "--root", self.root, "--capability", "烧录", "--json")
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(payload["returned"], 1)
        self.assertEqual(payload["entries"][0]["source_skill"], "cskflashtest")

    def test_stale_hidden_unless_requested(self) -> None:
        record(self.root, write_receipt(self.root, lessons=[lesson()]))
        entries = self.entries()
        for entry in entries:
            entry["status"] = "stale"
        kb.save_entries(self.root, entries)
        code, out, _ = run_kb("query", "--root", self.root, "--device", "bench-a", "--json")
        self.assertEqual(json.loads(out)["returned"], 0)
        code, out, _ = run_kb("query", "--root", self.root, "--device", "bench-a", "--include-stale", "--json")
        self.assertGreaterEqual(json.loads(out)["returned"], 1)

    def test_query_output_has_no_full_text(self) -> None:
        long_claim = "很长的结论" * 100
        record(self.root, write_receipt(self.root, lessons=[lesson(claim=long_claim)]))
        _, out, _ = run_kb("query", "--root", self.root, "--device", "bench-a")
        self.assertNotIn(long_claim, out)


class LintTests(KBTestBase):
    def _write_knowledge(self, rows: list[dict]) -> None:
        path = self.root / "entries" / "knowledge" / "entries.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def _valid_row(self, entry_id: str = "kb-knowledge-aaaaaaaaaaaa", **overrides) -> dict:
        row = {
            "schema": "entry.v1",
            "id": entry_id,
            "type": "knowledge",
            "scope": {"device": "bench-a", "project": "通用", "firmware": None, "platform": "linux"},
            "title": "标题",
            "claim": "结论",
            "evidence": [{"kind": "issue", "ref": "NOAH-7"}],
            "confidence": "medium",
            "status": "pending",
            "superseded_by": None,
            "source_skill": None,
            "created": "2026-11-06T10:00:00Z",
            "updated": "2026-11-06T10:00:00Z",
            "hits": 0,
            "validations": ["run-x"],
        }
        row.update(overrides)
        return row

    def test_lint_reports_bad_entries(self) -> None:
        rows = [
            self._valid_row(scope="bench-a"),
            self._valid_row(id="kb-knowledge-aaaaaaaaaaaa"),
            self._valid_row(id="kb-knowledge-bbbbbbbbbbbb", status="superseded", superseded_by="kb-knowledge-ffffffffffff"),
            self._valid_row(id="kb-knowledge-cccccccccccc", foo="bar"),
            self._valid_row(id="kb-knowledge-dddddddddddd", evidence="oops"),
        ]
        self._write_knowledge(rows)
        code, out, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 3)
        self.assertIn("类型应为", out)
        self.assertIn("重复条目 id", out)
        self.assertIn("superseded_by 指向不存在的条目", out)
        self.assertIn("未定义字段 foo", out)

    def test_lint_reports_index_drift(self) -> None:
        record(self.root, write_receipt(self.root, lessons=[lesson()]))
        path = self.root / "index" / "by-device.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["keys"] = {}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        code, out, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 3)
        self.assertIn("缺少键", out)
        code, _, err = run_kb("index", "--root", self.root)
        self.assertEqual(code, 0, err)
        code, out, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 0, out)

    def test_lint_detects_secret(self) -> None:
        self._write_knowledge([self._valid_row(claim="包含 FAKE_SECRET_ABCDEF12 的配置")])
        code, out, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 3)
        self.assertIn("凭据规则命中", out)
        self.assertNotIn("FAKE_SECRET_ABCDEF12", out)

    def test_unknown_skill_warns_but_strict_fails(self) -> None:
        record(self.root, write_receipt(self.root, skill="no-such-skill", lessons=[lesson()]))
        code, out, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 0, out)
        self.assertIn("未在台账登记", out)
        code, _, _ = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME, "--strict")
        self.assertEqual(code, 3)


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.bare = self.tmp / "remote.git"
        self.work = make_kb(self.tmp / "kb")
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.bare)], check=True,
                       capture_output=True)
        self.git("init", "-b", "main")
        self.git("add", "-A")
        self.commit("init")
        self.git("remote", "add", "origin", str(self.bare))
        self.git("push", "-u", "origin", "main")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.work, check=True, capture_output=True, text=True)

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message],
                       cwd=self.work, check=True, capture_output=True)

    def test_sync_refuses_main_push(self) -> None:
        code, _, err = run_kb("sync", "--root", self.work, "--push", "--no-pull")
        self.assertEqual(code, 3)
        self.assertIn("拒绝直接推送", err)

    def test_sync_pushes_feature_branch_only(self) -> None:
        self.git("checkout", "-b", "feature/kb-test")
        (self.work / "entries" / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.work / "entries" / "knowledge" / "entries.jsonl").write_text("", encoding="utf-8")
        self.git("add", "-A")
        self.commit("kb entry")
        code, _, err = run_kb("sync", "--root", self.work, "--push", "--no-pull")
        self.assertEqual(code, 0, err)
        heads = subprocess.run(["git", "--git-dir", str(self.bare), "rev-parse", "--verify",
                                "refs/heads/feature/kb-test"], check=True, capture_output=True, text=True)
        self.assertTrue(heads.stdout.strip())

    def test_sync_pulls_upstream(self) -> None:
        other = self.tmp / "other"
        subprocess.run(["git", "clone", str(self.bare), str(other)], check=True, capture_output=True)
        (other / "pulled.txt").write_text("from upstream\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-m", "up"],
                       cwd=other, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=other, check=True, capture_output=True)
        code, _, err = run_kb("sync", "--root", self.work)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.work / "pulled.txt").is_file())


class SchemaTests(KBTestBase):
    def test_generated_entries_conform_to_schema(self) -> None:
        record(self.root, write_receipt(self.root, lessons=[lesson()], bugs=[{"title": "t", "claim": "c"}]))
        schema = json.loads((SCHEMA / "entry.v1.json").read_text(encoding="utf-8"))
        for entry in self.entries():
            self.assertEqual(kb.validate(entry, schema), [], entry["id"])

    def test_receipt_schema_requires_core_fields(self) -> None:
        schema = json.loads((SCHEMA / "receipt.v1.json").read_text(encoding="utf-8"))
        errors = kb.validate({}, schema)
        self.assertTrue(any("缺少必填字段 run_id" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
