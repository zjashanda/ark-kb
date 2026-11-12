"""TTS 资产索引单测：asset-record / asset-query / index / lint。

所有用例在临时目录里复制 schema、entries、registry 后运行，
不触碰仓库真实的 entries/、index/ 与 receipts/。
"""

from __future__ import annotations

import io
import json
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
CREATED = "2026-11-12 17:05:00"
KEY = "0123456789abcdef" + "0" * 48
SHA = "a" * 64
SHA2 = "b" * 64
ASSET = "tts-" + KEY[:16]
ASSET_V2 = ASSET + "-v2"


def run_kb(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = kb.main([str(item) for item in argv])
    return code, out.getvalue(), err.getvalue()


def make_kb(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "schema").mkdir(exist_ok=True)
    for name in ("entry.v1.json", "receipt.v1.json", "index.v1.json",
                 "kb-context.v1.json", "delivery.v1.json", "checkpoint.v1.json",
                 "asset-entry.v1.json"):
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


def manifest(asset_id: str = ASSET, sha: str = SHA, **overrides) -> dict:
    data = {
        "schema": "ark.tts-asset.v1",
        "asset_id": asset_id,
        "cache_key": KEY,
        "status": "active",
        "quality": "formal",
        "shareable": True,
        "sensitivity": "none",
        "scope": {"visibility": "public", "projects": [], "nodes": []},
        "text": {"raw_sha256": SHA, "normalized": "这是一句用于索引测试的短文本", "language": "ZH"},
        "voice": {"speaker": "付小春", "voice_ref_sha256": None},
        "engine": {"engine": "lstts", "model": "IndexTTS", "model_version": "unknown"},
        "audio": {"filename": f"{sha}.wav", "bytes": 123456, "sha256": sha, "duration_seconds": 3.2},
        "provenance": {"generated_at": CREATED, "node": "bszT14", "tool": "tts-runtime"},
        "supersedes": None,
        "superseded_by": None,
        "created_at": CREATED,
    }
    data.update(overrides)
    return data


def write_manifest(root: Path, name: str, data: dict) -> Path:
    path = root / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def record(root: Path, data: dict, *extra, name: str = "manifest.json") -> tuple[int, str, str]:
    path = write_manifest(root, name, data)
    return run_kb("asset-record", "--root", root, "--asset", path,
                  "--skill-git-home", SCANNER_HOME, *extra)


def rows(root: Path) -> list[dict]:
    return kb.load_asset_entries(root)


class AssetIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_kb(self.tmp / "kb")
        self.addCleanup(self._tmp.cleanup)

    def test_record_then_query_hit(self) -> None:
        code, out, err = record(self.root, manifest(), "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(rows(self.root)), 1)

        code, out, err = run_kb("asset-query", "--root", self.root, "--voice", "付小春",
                                "--language", "ZH", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["entries"][0]["asset_id"], ASSET)
        self.assertEqual(payload["entries"][0]["match"], "candidate")
        self.assertTrue(payload["index_only"])
        self.assertIn("asset-tools", payload["note"])

        code, out, err = run_kb("asset-query", "--root", self.root, "--asset-id", ASSET, "--json")
        self.assertEqual(json.loads(out)["entries"][0]["match"], "exact")

    def test_replay_same_asset_is_idempotent(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        code, out, err = record(self.root, manifest(), "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["idempotent"])
        self.assertFalse(payload["created"])
        self.assertEqual(len(rows(self.root)), 1)
        self.assertEqual(rows(self.root)[0]["audio_sha256"], SHA)

    def test_versioned_supersede_flow(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        v2 = manifest(asset_id=ASSET_V2, sha=SHA2, supersedes=ASSET)
        self.assertEqual(record(self.root, v2, "--json")[0], 0)
        by_id = {row["asset_id"]: row for row in rows(self.root)}
        self.assertIsNone(by_id[ASSET]["superseded_by"])
        self.assertEqual(by_id[ASSET]["status"], "active")

        code, out, err = record(self.root, v2, "--supersede", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["superseded"]["asset_id"], ASSET)
        by_id = {row["asset_id"]: row for row in rows(self.root)}
        self.assertEqual(by_id[ASSET]["status"], "superseded")
        self.assertEqual(by_id[ASSET]["superseded_by"], ASSET_V2)
        self.assertEqual(by_id[ASSET_V2]["status"], "active")

        code, out, err = run_kb("asset-query", "--root", self.root, "--json")
        self.assertEqual([item["asset_id"] for item in json.loads(out)["entries"]], [ASSET_V2])
        code, out, err = run_kb("asset-query", "--root", self.root, "--include-stale", "--json")
        self.assertEqual({item["asset_id"] for item in json.loads(out)["entries"]}, {ASSET, ASSET_V2})

    def test_same_asset_different_sha_requires_version(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        code, out, err = record(self.root, manifest(sha=SHA2))
        self.assertEqual(code, 2)
        self.assertIn("ASSET_VERSION_CONFLICT", err)
        self.assertEqual(len(rows(self.root)), 1)

    def test_stale_excluded_unless_include_stale(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        code, out, err = record(self.root, manifest(status="stale"), "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(rows(self.root)[0]["status"], "stale")

        code, out, err = run_kb("asset-query", "--root", self.root, "--voice", "付小春", "--json")
        self.assertEqual(json.loads(out)["total"], 0)
        code, out, err = run_kb("asset-query", "--root", self.root, "--voice", "付小春",
                                "--include-stale", "--json")
        self.assertEqual(json.loads(out)["total"], 1)

        self.assertEqual(record(self.root, manifest(), "--json")[0], 0)
        self.assertEqual(rows(self.root)[0]["status"], "stale")

    def test_invalid_manifest_rejected_without_partial_write(self) -> None:
        path = self.root / "missing.json"
        code, out, err = run_kb("asset-record", "--root", self.root, "--asset", path,
                                "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 2)
        self.assertFalse(kb.asset_entry_file(self.root).is_file())

        bad_json = self.root / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        code, out, err = run_kb("asset-record", "--root", self.root, "--asset", bad_json,
                                "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 2)
        self.assertFalse(kb.asset_entry_file(self.root).is_file())

        broken = manifest(asset_id="tts-not-a-key")
        broken["library_path"] = "/srv/storage/ark/artifacts/audio/tts-library/x.wav"
        code, out, err = record(self.root, broken)
        self.assertEqual(code, 2)
        self.assertFalse(kb.asset_entry_file(self.root).is_file())

    def test_index_rebuild_includes_asset_entries(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        index_path = kb.asset_index_file(self.root)
        self.assertTrue(index_path.is_file())
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "ark.tts-asset-index.v1")
        self.assertIn(ASSET, payload["by_voice"][kb.norm_text("付小春")])

        index_path.unlink()
        code, out, err = run_kb("index", "--root", self.root)
        self.assertEqual(code, 0, err)
        rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt["by_engine"], payload["by_engine"])

        code, out, err = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 0, out + err)

    def test_no_absolute_path_or_credential_written(self) -> None:
        code, out, err = record(self.root, manifest(summary="TTS 索引摘要"))
        self.assertEqual(code, 0, err)
        text = kb.asset_entry_file(self.root).read_text(encoding="utf-8")
        self.assertNotIn("/srv/", text)
        self.assertNotIn("10027", text)
        self.assertNotIn("FAKE_SECRET", text)
        entry = json.loads(text)
        for key in ("text", "audio", "normalized", "raw_sha256", "token"):
            self.assertNotIn(key, entry)

        before = text
        code, out, err = record(self.root, manifest(summary="FAKE_SECRET_abcdef123456"))
        self.assertNotEqual(code, 0)
        self.assertEqual(kb.asset_entry_file(self.root).read_text(encoding="utf-8"), before)

    def test_lint_detects_asset_index_drift(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        index_path = kb.asset_index_file(self.root)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["by_voice"] = {}
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        code, out, err = run_kb("lint", "--root", self.root, "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 3)
        self.assertIn("资产索引漂移", out)

    def test_acl_scope_filters(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        scoped = manifest(asset_id=ASSET_V2, sha=SHA2,
                          scope={"visibility": "project", "projects": ["CSK5062"], "nodes": []})
        self.assertEqual(record(self.root, scoped)[0], 0)

        code, out, err = run_kb("asset-query", "--root", self.root, "--json")
        self.assertEqual([item["asset_id"] for item in json.loads(out)["entries"]], [ASSET])
        code, out, err = run_kb("asset-query", "--root", self.root,
                                "--project", "CSK5062", "--json")
        self.assertEqual({item["asset_id"] for item in json.loads(out)["entries"]},
                         {ASSET, ASSET_V2})
        code, out, err = run_kb("asset-query", "--root", self.root,
                                "--project", "OTHER", "--scope", "project", "--json")
        self.assertEqual(json.loads(out)["total"], 0)

    def test_existing_kb_entries_and_receipt_unaffected(self) -> None:
        self.assertEqual(record(self.root, manifest())[0], 0)
        knowledge = kb.entry_file(self.root, "knowledge")
        seeded = knowledge.read_text(encoding="utf-8")
        by_device = (self.root / "index" / "by-device.json").read_text(encoding="utf-8")
        self.assertEqual(record(self.root, manifest(asset_id=ASSET_V2, sha=SHA2))[0], 0)
        self.assertEqual(knowledge.read_text(encoding="utf-8"), seeded)
        self.assertEqual((self.root / "index" / "by-device.json").read_text(encoding="utf-8"),
                         by_device)
        self.assertTrue((self.root / "index" / "asset-index.json").is_file())

    def test_ark_archive_receipt_still_records(self) -> None:
        source = REPO / "docs" / "receipts" / "20261106-kb-selftest"
        target = self.root / "receipts" / "20261106-kb-selftest"
        shutil.copytree(source, target)
        receipt = target / "run.receipt.json"
        code, out, err = run_kb("record", "--root", self.root, "--receipt", receipt,
                                "--skill-git-home", SCANNER_HOME)
        self.assertEqual(code, 0, err)
        knowledge = kb.entry_file(self.root, "knowledge")
        self.assertGreater(len([line for line in knowledge.read_text(encoding="utf-8").splitlines() if line.strip()]), 0)
        before_entries = {name: kb.entry_file(self.root, name).read_text(encoding="utf-8")
                          for name in kb.ENTRY_TYPES}
        self.assertEqual(record(self.root, manifest())[0], 0)
        for name, text in before_entries.items():
            self.assertEqual(kb.entry_file(self.root, name).read_text(encoding="utf-8"), text)

    def test_empty_query_is_index_hint_not_library_absence(self) -> None:
        code, out, err = run_kb("asset-query", "--root", self.root, "--voice", "无人")
        self.assertEqual(code, 0, err)
        self.assertIn("不代表 1006 库里不存在", out)


if __name__ == "__main__":
    unittest.main()
