"""ark-mesh 单测：离线，不连任何节点、不碰网络。"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ark_fetch  # noqa: E402

CFG = {
    "schema": "ark-mesh-sources.v1",
    "nodes": {
        "win-a": {"kind": "windows", "host": "10.0.0.11", "port": 22, "user": "administrator"},
        "win-b": {"kind": "windows", "host": "10.0.0.12", "port": 22, "user": "administrator"},
    },
    "artifacts": {},
}


def write_cfg(root: Path, cfg: dict) -> Path:
    path = root / "sources.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return path


class GuardTests(unittest.TestCase):
    def test_rejects_credential_paths(self) -> None:
        bad = [
            r"D:\work\.env",
            r"D:\work\prod.env",
            r"D:\work\github_token.txt",
            r"D:\work\id_rsa",
            r"D:\work\server.pem",
            r"/home/ops/.git-credentials",
            r"D:\work\auth.json",
            r"D:\work\sub\password.txt",
            r"D:\work\tls.p12",
            r"D:\work\netrc",
        ]
        for path in bad:
            with self.subTest(path=path), self.assertRaises(SystemExit) as ctx, \
                    redirect_stderr(io.StringIO()):
                ark_fetch.guard({"name": "x", "path": path})
            self.assertEqual(ctx.exception.code, ark_fetch.EXIT_FORBIDDEN)

    def test_allows_normal_artifacts(self) -> None:
        ok = [
            r"D:\zhsh\workspace\artifacts\HAS_TCL_CSK7_HI3863_LZX_20261103_TEST_V0.0.41.zip",
            r"D:\burn\V12.1.25\CSK\Uart_Burn_Tool.exe",
            "/srv/storage/ark/artifacts/noah-37/V12.1.25/Uart_Burn_Tool.exe",
            "V8-H363T20-WFMV206.111.1.16.bin",
            "/data/corpus/keyword-list.txt",
        ]
        for path in ok:
            with self.subTest(path=path):
                ark_fetch.guard({"name": "x", "path": path})


class LevelTests(unittest.TestCase):
    def test_priority_then_declaration_order(self) -> None:
        art = {"locations": [
            {"node": "win-b", "path": "p2", "priority": 2},
            {"node": "win-a", "path": "p1", "priority": 1},
            {"node": "win-c", "path": "p1b", "priority": 1},
        ]}
        order = [loc["path"] for loc in ark_fetch.candidates(CFG, art, set())]
        self.assertEqual(order, ["p1", "p1b", "p2"])

    def test_skip_node_removes_source(self) -> None:
        art = {"locations": [{"node": "win-a", "path": "p", "priority": 1},
                             {"node": "win-b", "path": "p", "priority": 2}]}
        order = [loc["node"] for loc in ark_fetch.candidates(CFG, art, {"win-a"})]
        self.assertEqual(order, ["win-b"])


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.record = {
            "name": "fw", "project": "p", "version": "V1",
            "source_node": "win-a", "source_path": r"D:\a\fw.bin",
            "destination": r"D:\dest\fw.bin", "bytes": 3,
            "sha256": "a" * 64, "fetched_at": "2026-11-09T10:00:00+08:00",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_is_idempotent(self) -> None:
        ark_fetch.write_manifest(self.root, self.record, local=True)
        ark_fetch.write_manifest(self.root, self.record, local=True)
        data = json.loads((self.root / ark_fetch.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "ark-artifact-manifest.v1")
        self.assertEqual(len(data["artifacts"]), 1)
        self.assertEqual(data["artifacts"][0]["sha256"], "a" * 64)
        self.assertTrue(data["artifacts"][0]["destination"].endswith("fw.bin"))

    def test_different_hash_appends(self) -> None:
        ark_fetch.write_manifest(self.root, self.record, local=True)
        ark_fetch.write_manifest(self.root, dict(self.record, sha256="b" * 64), local=True)
        data = json.loads((self.root / ark_fetch.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(data["artifacts"]), 2)

    def test_corrupt_manifest_is_replaced(self) -> None:
        (self.root / ark_fetch.MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        ark_fetch.write_manifest(self.root, self.record, local=True)
        data = json.loads((self.root / ark_fetch.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(data["artifacts"]), 1)

    def test_record_has_required_fields(self) -> None:
        required = {"name", "project", "version", "source_node", "source_path",
                    "destination", "bytes", "sha256", "fetched_at"}
        self.assertTrue(required.issubset(self.record))


class FailureReportTests(unittest.TestCase):
    def test_report_lists_every_attempt_and_next_steps(self) -> None:
        cfg = dict(CFG, _path="/tmp/sources.json")
        art = {"name": "fw", "project": "p", "version": "V1", "locations": [
            {"node": "win-a", "path": r"D:\a\fw.bin", "priority": 1},
            {"node": "win-b", "path": r"D:\b\fw.bin", "priority": 2},
        ]}
        attempts = [
            {"source_node": "win-a", "source_path": r"D:\a\fw.bin", "result": "unreachable",
             "error": "Connection refused", "elapsed_s": 0.1},
            {"source_node": "win-b", "source_path": r"D:\b\fw.bin", "result": "source_unusable",
             "error": "源文件不存在", "elapsed_s": 1.2},
        ]
        report = ark_fetch.build_failure_report(art, "fw", attempts, "所有来源均失败",
                                               cfg=cfg, dest_node=None, dest_dir="/tmp/d")
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertEqual(len(report["attempts"]), 2)
        self.assertTrue(all("error" in a for a in report["attempts"]))
        self.assertTrue(report["next_steps"])
        self.assertIn("win-b", " ".join(report["next_steps"]))

    def test_failure_report_written(self) -> None:
        cfg = dict(CFG, _path="/tmp/sources.json")
        report = ark_fetch.build_failure_report(None, "ghost", [], "制品未登记", cfg=cfg,
                                               dest_node=None, dest_dir=self._tmp())
        ark_fetch._write_failure(report, self._tmp())
        path = Path(self._tmp()) / ark_fetch.FAILURE_NAME
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["verdict"], "BLOCKED")

    def _tmp(self) -> str:
        if not hasattr(self, "_dir"):
            self._tmpdir = tempfile.TemporaryDirectory()
            self._dir = self._tmpdir.name
        return self._dir


class CacheTests(unittest.TestCase):
    def test_cache_path_uses_hash_prefix(self) -> None:
        cfg = {"cache": {"dir": "/tmp/ark-cache-test"}}
        art = {"name": "fw", "sha256": "c" * 64, "filename": "fw.bin"}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARK_MESH_CACHE", None)
            path = ark_fetch.cache_path(cfg, art)
        self.assertEqual(path.name, "fw.bin")
        self.assertEqual(path.parent.name, "c" * 16)

    def test_env_overrides_cache_dir(self) -> None:
        cfg = {"cache": {"dir": "/tmp/ignored"}}
        art = {"name": "fw", "sha256": "d" * 64, "filename": "fw.bin"}
        with mock.patch.dict(os.environ, {"ARK_MESH_CACHE": "/tmp/override"}):
            path = ark_fetch.cache_path(cfg, art)
        self.assertEqual(str(path).split(os.sep)[1], "tmp")
        self.assertEqual(path.parent.parent.name, "override")


class ConfigTests(unittest.TestCase):
    def test_schema_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_cfg(Path(tmp), {"schema": "wrong", "nodes": {}})
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                ark_fetch.load_config(path)

    def test_missing_config_rejected(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            ark_fetch.load_config(Path("/nonexistent/ark/mesh-sources.json"))

    def test_index_add_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_cfg(root, dict(CFG, artifacts={}))
            cfg = ark_fetch.load_config(path)
            cfg["artifacts"]["fw"] = {"name": "fw", "locations": []}
            cfg["artifacts"]["fw"]["locations"].append({"node": "win-a", "path": r"D:\a\fw.bin", "priority": 1})
            ark_fetch.save_config(cfg)
            again = ark_fetch.load_config(path)
            self.assertEqual(again["artifacts"]["fw"]["locations"][0]["node"], "win-a")
            self.assertIn("_path", again)


class NodeSpecTests(unittest.TestCase):
    def test_unknown_node_exits(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            ark_fetch.node_spec(CFG, "nope")

    def test_windows_detection(self) -> None:
        self.assertTrue(ark_fetch.is_windows(CFG["nodes"]["win-a"]))
        self.assertFalse(ark_fetch.is_windows({"kind": "linux"}))


if __name__ == "__main__":
    unittest.main()
