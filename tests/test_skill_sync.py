"""skill_sync 单测：纯离线，不访问网络。

覆盖三类行为：
1. classify() 的状态矩阵（本地事实优先于远端/归档）；
2. assemble 的 manifest 结构与 applied 作用域；
3. apply 的安全快进：dry-run 不写、--apply 只做 fast-forward、脏工作区不动。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import skill_sync  # noqa: E402


def entry(**kw):
    base = {
        "name": "Polaris",
        "kind": "checkout",
        "path": "/hub/Polaris",
        "git": True,
        "branch": "main",
        "sha": "a" * 40,
        "cache_sha": "a" * 40,
        "dirty_tracked": 0,
        "untracked": 0,
    }
    base.update(kw)
    return base


def row(**kw):
    base = {"name": "Polaris", "status": "active"}
    base.update(kw)
    return base


class ClassifyTest(unittest.TestCase):
    def test_absent(self):
        self.assertEqual(skill_sync.classify(None, row(), "a" * 40, "public", set())[0], "ABSENT")

    def test_in_sync(self):
        self.assertEqual(skill_sync.classify(entry(), row(), "a" * 40, "public", set())[0],
                         "IN_SYNC")

    def test_outdated(self):
        self.assertEqual(skill_sync.classify(entry(), row(), "b" * 40, "public", set())[0],
                         "OUTDATED")

    def test_drift_beats_archive_and_remote(self):
        got = skill_sync.classify(entry(dirty_tracked=3), row(status="archived"), None, "public", set())
        self.assertEqual(got[0], "LOCAL_DRIFT")

    def test_unmanaged_copy(self):
        got = skill_sync.classify(entry(git=False, sha=""), row(), "a" * 40, "public", set())
        self.assertEqual(got[0], "UNMANAGED_COPY")

    def test_cache_only_is_missing_checkout(self):
        got = skill_sync.classify(entry(kind="cache", sha=""), row(), "a" * 40, "public", set())
        self.assertEqual(got[0], "MISSING_CHECKOUT")

    def test_private_repo_on_public_node(self):
        got = skill_sync.classify(entry(), row(name="fileball"), "a" * 40, "public", {"fileball"})
        self.assertEqual(got[0], "REMOTE_UNREACHABLE")

    def test_private_repo_on_control_node(self):
        got = skill_sync.classify(entry(), row(name="fileball"), "a" * 40, "full", {"fileball"})
        self.assertEqual(got[0], "IN_SYNC")

    def test_archived_clean_is_archived(self):
        got = skill_sync.classify(entry(), row(status="archived"), "a" * 40, "public", set())
        self.assertEqual(got[0], "ARCHIVED")

    def test_untracked_only_is_not_drift(self):
        got = skill_sync.classify(entry(untracked=7), row(), "a" * 40, "public", set())
        self.assertEqual(got[0], "IN_SYNC")

    def test_unknown_remote_is_unreachable(self):
        got = skill_sync.classify(entry(), row(), None, "public", set())
        self.assertEqual(got[0], "REMOTE_UNREACHABLE")


class AssembleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-sync-test-"))
        self.registry = self.tmp / "skills.json"
        self.nodes = self.tmp / "nodes.json"
        self.remote = self.tmp / "remote.json"
        self.inv = self.tmp / "inv.json"
        self.out = self.tmp / "manifest.json"
        self.registry.write_text(json.dumps([
            {"name": "Polaris", "status": "active"},
            {"name": "lstest", "status": "active"},
            {"name": "listenai-laid-installer", "status": "archived"},
        ]), encoding="utf-8")
        self.nodes.write_text(json.dumps({
            "schema": "skillhub-nodes.v1",
            "github": {"private_repos": ["fileball"]},
            "nodes": [
                {"node": "bszT14", "endpoint": "x", "os": "linux", "hub": "/hub",
                 "github_access": "full"},
                {"node": "win000", "endpoint": "y", "os": "windows", "hub": "D:\\hub",
                 "github_access": "public"},
            ],
        }), encoding="utf-8")
        self.remote.write_text(json.dumps({
            "schema": "skill-remote-shas.v1", "ok": 2, "failed": 1,
            "skills": [
                {"name": "Polaris", "sha": "a" * 40, "error": None},
                {"name": "lstest", "sha": "c" * 40, "error": None},
                {"name": "listenai-laid-installer", "sha": None, "error": "boom"},
            ],
        }), encoding="utf-8")
        self.inv.write_text(json.dumps({
            "schema": "skillhub-inventory.v1", "node": "WIN000", "os": "windows", "hub": "D:\\hub",
            "entries": [
                entry(name="Polaris", sha="d" * 40),
                {"name": "tcl-device-autoburn", "kind": "checkout", "path": "p", "git": False,
                 "branch": "", "sha": "", "cache_sha": "", "dirty_tracked": 0, "untracked": 0},
                {"name": "Polaris.broken-1-aa", "kind": "other", "path": "q", "git": True,
                 "branch": "main", "sha": "e" * 40, "cache_sha": "", "dirty_tracked": 0,
                 "untracked": 0},
            ],
        }), encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _assemble(self, *extra):
        argv = ["assemble", "--registry", str(self.registry), "--nodes", str(self.nodes),
                "--remote", str(self.remote), "--inventory", str(self.inv),
                "--out", str(self.out)] + list(extra)
        self.assertEqual(skill_sync.main(argv), 0)
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_structure_and_counts(self):
        doc = self._assemble()
        self.assertEqual(doc["schema"], "skill-sync-manifest.v1")
        self.assertEqual(doc["summary"]["nodes"], 2)
        win = [n for n in doc["nodes"] if n["node"] == "win000"][0]
        states = {s["name"]: s["state"] for s in win["skills"]}
        self.assertEqual(states["Polaris"], "OUTDATED")
        self.assertIn("lstest", win["absent"])
        self.assertEqual(win["counts"]["PRIVATE_SKILL"], 1)
        self.assertEqual(len(win["broken_copies"]), 1)
        bsz = [n for n in doc["nodes"] if n["node"] == "bszT14"][0]
        self.assertFalse(bsz["inventory_present"])
        self.assertEqual(bsz["counts"]["ABSENT"], 3)

    def test_applied_only_affects_its_hub(self):
        applied = self.tmp / "applied.json"
        applied.write_text(json.dumps({
            "schema": "skillhub-apply.v1", "hub": "D:\\hub", "apply": True,
            "entries": [{"name": "Polaris", "state": "UPDATED",
                         "from_sha": "d" * 40, "to_sha": "a" * 40}],
        }), encoding="utf-8")
        doc = self._assemble("--applied", str(applied))
        win = [n for n in doc["nodes"] if n["node"] == "win000"][0]
        states = {s["name"]: s["state"] for s in win["skills"]}
        self.assertEqual(states["Polaris"], "UPDATED")
        bsz = [n for n in doc["nodes"] if n["node"] == "bszT14"][0]
        self.assertEqual(bsz["counts"]["UPDATED"], 0)


def _git(*args, cwd=None):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


class ApplyTest(unittest.TestCase):
    """真实临时仓库：只验证快进与不越权。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-apply-test-"))
        self.upstream = self.tmp / "upstream"
        self.upstream.mkdir()
        _git("init", "-q", "--bare", str(self.upstream))
        self.seed = self.tmp / "seed"
        _git("clone", "-q", str(self.upstream), str(self.seed))
        _git("config", "user.email", "t@example.com", cwd=self.seed)
        _git("config", "user.name", "t", cwd=self.seed)
        (self.seed / "SKILL.md").write_text("v1\n")
        _git("add", ".", cwd=self.seed)
        _git("commit", "-q", "-m", "v1", cwd=self.seed)
        _git("push", "-q", "origin", "HEAD:main", cwd=self.seed)
        _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.upstream)
        self.first = _git("rev-parse", "HEAD", cwd=self.seed)

        self.registry = self.tmp / "skills.json"
        self.registry.write_text(json.dumps([{"name": "demo", "status": "active"}]),
                                 encoding="utf-8")
        self.hub = self.tmp / "hub"
        (self.hub / "cache").mkdir(parents=True)
        _git("clone", "-q", "--bare", str(self.upstream), str(self.hub / "cache" / "demo.git"))
        _git("clone", "-q", str(self.hub / "cache" / "demo.git"), str(self.hub / "demo"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _apply(self, *extra):
        return skill_sync.main(["apply", "--hub", str(self.hub), "--registry", str(self.registry),
                                "--skills", "demo"] + list(extra))

    def _advance_remote(self):
        (self.seed / "SKILL.md").write_text("v2\n")
        _git("commit", "-qam", "v2", cwd=self.seed)
        _git("push", "-q", "origin", "HEAD:main", cwd=self.seed)
        return _git("rev-parse", "HEAD", cwd=self.seed)

    def test_dry_run_does_not_write(self):
        second = self._advance_remote()
        self.assertEqual(self._apply("--json"), 0)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.hub / "demo"), self.first)
        self.assertNotEqual(second, self.first)

    def test_apply_fast_forwards(self):
        second = self._advance_remote()
        self.assertEqual(self._apply("--apply", "--json"), 0)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.hub / "demo"), second)

    def test_dirty_checkout_is_left_alone(self):
        second = self._advance_remote()
        target = self.hub / "demo" / "SKILL.md"
        target.write_text("local edit\n")
        self.assertEqual(self._apply("--apply", "--json"), 0)
        self.assertEqual(target.read_text(), "local edit\n")
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.hub / "demo"), self.first)
        self.assertNotEqual(second, self.first)


if __name__ == "__main__":
    unittest.main()
