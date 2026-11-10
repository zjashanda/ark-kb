#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_sync.py - NoahsArk skillhub 版本清点与同步（控制节点侧）。

三个子命令：

  remote-shas   采集 35 个 GitHub skill 的远端 SHA（控制节点用 SSH 别名访问）
  assemble      把各节点 inventory + 远端 SHA + 台账合成 skill-sync-manifest.json
  apply         在控制节点自己的 hub 上做安全快进（默认 dry-run）

设计原则：节点侧只用 git，不做推断；控制节点只汇总与安全快进。
绝不删除、绝不 reset --hard、绝不 clean、绝不覆盖有本地修改的检出。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STATES = [
    "REMOTE_UNREACHABLE",
    "ARCHIVED",
    "UNMANAGED_COPY",
    "LOCAL_DRIFT",
    "IN_SYNC",
    "OUTDATED",
    "MISSING_CHECKOUT",
    "UPDATED",
    "AHEAD",
    "PRIVATE_SKILL",
    "ABSENT",
]

GIT_ENV = dict(os.environ)
GIT_ENV.update(
    {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "C",
        "GIT_ASKPASS": "/bin/true",
    }
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git(args, timeout=180, ssh_alias=None):
    """执行 git 命令，返回 (rc, stdout, stderr)。永不抛异常。"""
    env = dict(GIT_ENV)
    if ssh_alias:
        env["GIT_SSH_COMMAND"] = (
            "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"
        )
    try:
        p = subprocess.run(
            ["git", "-c", "credential.helper=", "-c", "http.lowSpeedLimit=1",
             "-c", "http.lowSpeedTime=60"] + list(args),
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "git not found"


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path, obj):
    p = Path(path)
    if p.parent and str(p.parent) != ".":
        p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


# --------------------------------------------------------------------------
# remote-shas
# --------------------------------------------------------------------------
def resolve_remote(alias: str, name: str, timeout: int = 60):
    url = "{}:zjashanda/{}.git".format(alias, name)
    rc, out, err = git(["ls-remote", "--symref", url, "HEAD", "refs/heads/main"],
                       timeout=timeout, ssh_alias=alias)
    if rc != 0:
        return {"name": name, "sha": None, "ref": None, "default_branch": None,
                "error": (err or out or "rc={}".format(rc)).splitlines()[0][:200]}
    head_sha = None
    main_sha = None
    default_branch = None
    for line in out.splitlines():
        if line.startswith("ref:") and "\tHEAD" in line:
            default_branch = line.split()[1].replace("refs/heads/", "")
        elif line.endswith("\trefs/heads/main"):
            main_sha = line.split("\t")[0]
        elif line.endswith("\tHEAD"):
            head_sha = line.split("\t")[0]
    sha = main_sha or head_sha
    ref = "refs/heads/main" if main_sha else (
        "refs/heads/{}".format(default_branch) if default_branch else None)
    return {"name": name, "sha": sha, "ref": ref, "default_branch": default_branch,
            "error": None}


def cmd_remote_shas(args):
    registry = load_json(args.registry)
    alias = args.alias
    results = []
    for row in registry:
        res = resolve_remote(alias, row["name"], timeout=args.timeout)
        results.append(res)
    ok = sum(1 for r in results if r["sha"])
    doc = {
        "schema": "skill-remote-shas.v1",
        "generated_at": now_iso(),
        "alias": alias,
        "ok": ok,
        "failed": len(results) - ok,
        "skills": results,
    }
    dump_json(args.out, doc)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for r in results:
            state = r["sha"][:10] if r["sha"] else "ERR"
            print("{:<12} {:<28} {}".format(state, r["name"], r["error"] or r["ref"]))
    return 0 if ok else 3


# --------------------------------------------------------------------------
# assemble
# --------------------------------------------------------------------------
# 判定优先级：本地可观测事实（是否存在、是否被改过）永远先于远端与归档状态，
# 否则断网或"已归档"会把真实的本地修改藏起来。
PRECEDENCE = [
    "UNMANAGED_COPY",
    "LOCAL_DRIFT",
    "MISSING_CHECKOUT",
    "REMOTE_UNREACHABLE",
    "ARCHIVED",
    "IN_SYNC",
    "OUTDATED",
    "AHEAD",
]


def pick_entry(entries, name):
    """同一 skill 可能同时有 cache 与 checkout，取版本信息最全的那个。"""
    cands = [e for e in entries if e.get("name") == name and e.get("kind") != "other"]
    if not cands:
        return None
    rank = {"checkout": 0, "worktree": 1, "cache": 2}
    cands.sort(key=lambda e: rank.get(e.get("kind"), 9))
    return cands[0]


def classify(entry, row, remote_sha, node_github_access, private_repos):
    """返回 (state, detail)。优先级见 PRECEDENCE。"""
    if entry is None:
        return "ABSENT", "not in hub"
    if not entry.get("git"):
        return "UNMANAGED_COPY", "plain directory, not a git checkout"
    if entry.get("dirty_tracked", 0) > 0:
        return "LOCAL_DRIFT", "{} tracked change(s)".format(entry["dirty_tracked"])
    local = entry.get("sha") or ""
    if not local:
        return "MISSING_CHECKOUT", "no resolved commit (cache only)"
    remote_known = bool(remote_sha) and not (
        row["name"] in private_repos and node_github_access != "full"
    )
    if not remote_known:
        return "REMOTE_UNREACHABLE", "node cannot resolve remote sha"
    if row.get("status") == "archived":
        return "ARCHIVED", "registry status archived; local " + local[:8]
    if local == remote_sha:
        return "IN_SYNC", ""
    return "OUTDATED", "local != remote"


def cmd_assemble(args):
    registry = load_json(args.registry)
    nodes_doc = load_json(args.nodes)
    remote_doc = load_json(args.remote)
    remote_map = {r["name"]: r["sha"] for r in remote_doc.get("skills", [])}
    private_repos = set(nodes_doc.get("github", {}).get("private_repos", []))

    inv_by_node = {}
    for path in args.inventory or []:
        doc = load_json(path)
        inv_by_node[doc.get("node", "").lower()] = doc

    applied = {}
    applied_hub = None
    if args.applied:
        adoc = load_json(args.applied)
        applied_hub = adoc.get("hub")
        for e in adoc.get("entries", []):
            if e.get("state") == "UPDATED" and e.get("to_sha"):
                applied[e["name"]] = e

    registry_names = [r["name"] for r in registry]
    out_nodes = []
    totals = {s: 0 for s in STATES}

    for node in nodes_doc["nodes"]:
        key = node["node"].lower()
        inv = inv_by_node.get(key)
        entries = inv.get("entries", []) if inv else []
        skills = []
        absent = []
        private = []
        broken = []

        for e in entries:
            if e.get("kind") == "other":
                broken.append({"name": e.get("name"), "path": e.get("path"),
                               "git": e.get("git")})
            elif e.get("name") not in registry_names:
                private.append({"name": e.get("name"), "kind": e.get("kind"),
                                "path": e.get("path"), "git": e.get("git")})

        applied_here = bool(applied) and applied_hub and (
            os.path.normpath(str(node.get("hub", ""))) == os.path.normpath(str(applied_hub)))
        counts = {s: 0 for s in STATES}
        for row in registry:
            entry = pick_entry(entries, row["name"])
            state, detail = classify(entry, row, remote_map.get(row["name"]),
                                     node.get("github_access", "public"), private_repos)
            if applied_here and row["name"] in applied and state in ("OUTDATED", "IN_SYNC"):
                ap = applied[row["name"]]
                skills.append({
                    "name": row["name"], "state": "UPDATED",
                    "registry_status": row.get("status"),
                    "remote_sha": remote_map.get(row["name"]),
                    "local_sha": ap.get("to_sha"),
                    "applied_from_sha": ap.get("from_sha"),
                    "kind": (entry or {}).get("kind"),
                    "branch": (entry or {}).get("branch", ""),
                    "dirty_tracked": (entry or {}).get("dirty_tracked", 0),
                    "untracked": (entry or {}).get("untracked", 0),
                    "detail": "applied this run",
                })
                counts["UPDATED"] += 1
                totals["UPDATED"] += 1
                continue
            if state == "ABSENT":
                absent.append(row["name"])
            else:
                skills.append({
                    "name": row["name"], "state": state,
                    "registry_status": row.get("status"),
                    "remote_sha": remote_map.get(row["name"]),
                    "local_sha": (entry or {}).get("sha") or None,
                    "kind": (entry or {}).get("kind"),
                    "branch": (entry or {}).get("branch", ""),
                    "dirty_tracked": (entry or {}).get("dirty_tracked", 0),
                    "untracked": (entry or {}).get("untracked", 0),
                    "detail": detail,
                })
            counts[state] += 1
            totals[state] += 1

        for p in private:
            counts["PRIVATE_SKILL"] += 1
            totals["PRIVATE_SKILL"] += 1

        out_nodes.append({
            "node": node["node"],
            "endpoint": node.get("endpoint"),
            "os": node.get("os"),
            "hub": node.get("hub"),
            "github_access": node.get("github_access"),
            "inventory_present": inv is not None,
            "error": None if inv else "no inventory",
            "counts": counts,
            "skills": skills,
            "absent": absent,
            "private_skills": private,
            "broken_copies": broken,
        })

    doc = {
        "schema": "skill-sync-manifest.v1",
        "generated_at": now_iso(),
        "registry": args.registry,
        "nodes_source": args.nodes,
        "summary": {
            "nodes": len(out_nodes),
            "nodes_with_inventory": sum(1 for n in out_nodes if n["inventory_present"]),
            "registry_skills": len(registry),
            "state_counts": totals,
        },
        "remote": {
            "generated_at": remote_doc.get("generated_at"),
            "ok": remote_doc.get("ok"),
            "failed": remote_doc.get("failed"),
            "failures": [{"name": r["name"], "error": r["error"]}
                         for r in remote_doc.get("skills", []) if not r.get("sha")],
        },
        "nodes": out_nodes,
    }
    dump_json(args.out, doc)
    if args.json:
        print(json.dumps(doc["summary"], ensure_ascii=False))
    else:
        print("manifest: {}".format(args.out))
        for n in out_nodes:
            present = ", ".join("{}={}".format(k, v) for k, v in n["counts"].items() if v)
            print("{:<10} inv={:<5} {}".format(n["node"], str(n["inventory_present"]), present))
    return 0


# --------------------------------------------------------------------------
# apply（控制节点本地 hub）
# --------------------------------------------------------------------------
def find_checkout(hub: Path, name: str):
    for cand in (hub / name, hub / "worktrees" / name):
        if (cand / ".git").exists():
            return cand
    return None


def cmd_apply(args):
    registry = load_json(args.registry)
    hub = Path(args.hub)
    wanted = [s.strip() for s in args.skills.split(",")] if args.skills else None
    rows = [r for r in registry if not wanted or r["name"] in wanted]
    if wanted:
        known = {r["name"] for r in rows}
        for w in wanted:
            if w not in known:
                rows.append({"name": w, "status": "unknown"})

    results = []
    for row in rows:
        name = row["name"]
        cache = hub / "cache" / (name + ".git")
        co = find_checkout(hub, name)
        rec = {"name": name, "state": None, "from_sha": None, "to_sha": None, "detail": ""}

        if not cache.exists() and co is None:
            rec.update(state="ABSENT", detail="no cache and no checkout")
            results.append(rec)
            continue

        fetch_src = "origin"
        if args.remote_base:
            # 无 HTTPS 出网的节点：直接从 SSH 别名取，不改动 origin 配置
            fetch_src = "{}/{}.git".format(args.remote_base.rstrip("/"), name)
        if cache.exists():
            rc, out, err = git(["-C", str(cache), "fetch", "--prune", fetch_src,
                                "+refs/heads/*:refs/remotes/origin/*"],
                               ssh_alias=args.remote_base or None)
            if rc != 0:
                rec.update(state="REMOTE_UNREACHABLE", detail=(err or out).splitlines()[0][:200])
                results.append(rec)
                continue

        rsha = None
        if cache.exists():
            for ref in ("refs/remotes/origin/main", "refs/remotes/origin/HEAD"):
                rc, out, _ = git(["-C", str(cache), "rev-parse", "--verify", "--quiet", ref])
                if rc == 0 and out:
                    rsha = out
                    break
        if not rsha:
            rec.update(state="REMOTE_UNREACHABLE", detail="cannot resolve remote sha")
            results.append(rec)
            continue

        if co is None:
            rec.update(state="MISSING_CHECKOUT", to_sha=rsha, detail="cache only")
            results.append(rec)
            continue

        rc, out, _ = git(["-C", str(co), "status", "--porcelain", "--untracked-files=no"])
        if rc == 0 and out:
            rec.update(state="LOCAL_DRIFT", to_sha=rsha,
                       detail="{} tracked change(s)".format(len(out.splitlines())))
            results.append(rec)
            continue

        rc, lsha, _ = git(["-C", str(co), "rev-parse", "--verify", "HEAD"])
        lsha = lsha or None
        rec["from_sha"] = lsha
        rec["to_sha"] = rsha
        # 祖先关系要在 cache 里判断：checkout 往往没有远端新对象
        anc_repo = str(cache) if cache.exists() else str(co)
        if lsha == rsha:
            rec.update(state="IN_SYNC")
        elif git(["-C", anc_repo, "merge-base", "--is-ancestor", lsha, rsha])[0] == 0:
            if args.apply:
                target = rsha
                if cache.exists() and git(["-C", str(co), "cat-file", "-e", rsha])[0] != 0:
                    rc, _, _ = git(["-C", str(co), "fetch", "--quiet", str(cache),
                                    "refs/remotes/origin/main"])
                    if rc == 0:
                        target = "FETCH_HEAD"
                rc, out, err = git(["-C", str(co), "merge", "--ff-only", target])
                if rc == 0:
                    rec.update(state="UPDATED", detail="fast-forward")
                else:
                    rec.update(state="LOCAL_DRIFT",
                               detail="ff failed: " + (err or out).splitlines()[0][:160])
            else:
                rec.update(state="OUTDATED", detail="fast-forward available (dry-run)")
        elif git(["-C", anc_repo, "merge-base", "--is-ancestor", rsha, lsha])[0] == 0:
            rec.update(state="AHEAD", detail="local ahead of origin")
        else:
            rec.update(state="LOCAL_DRIFT", detail="diverged")
        results.append(rec)

    doc = {
        "schema": "skillhub-apply.v1",
        "hub": str(hub),
        "apply": bool(args.apply),
        "generated_at": now_iso(),
        "entries": results,
    }
    if args.out:
        dump_json(args.out, doc)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print("{:<14} {:<28} {} -> {}".format(r["state"], r["name"],
                                                  (r["from_sha"] or "")[:8],
                                                  (r["to_sha"] or "")[:8]))
    drift = any(r["state"] == "LOCAL_DRIFT" for r in results)
    remote_err = any(r["state"] == "REMOTE_UNREACHABLE" for r in results)
    if args.fail_on_drift and drift:
        return 8
    if args.fail_on_remote and remote_err:
        return 3
    return 0


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="NoahsArk skillhub 版本清点与同步")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("remote-shas", help="采集远端 SHA")
    r.add_argument("--registry", default="registry/skills.json")
    r.add_argument("--out", required=True)
    r.add_argument("--alias", default="github-zjashanda")
    r.add_argument("--timeout", type=int, default=60)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_remote_shas)

    a = sub.add_parser("assemble", help="合成 manifest")
    a.add_argument("--registry", default="registry/skills.json")
    a.add_argument("--nodes", default="registry/nodes.json")
    a.add_argument("--remote", required=True)
    a.add_argument("--inventory", action="append", default=[])
    a.add_argument("--applied")
    a.add_argument("--out", default="registry/skill-sync-manifest.json")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_assemble)

    p = sub.add_parser("apply", help="控制节点 hub 安全快进")
    p.add_argument("--hub", required=True)
    p.add_argument("--registry", default="registry/skills.json")
    p.add_argument("--skills")
    p.add_argument("--apply", action="store_true", help="真正写入（默认 dry-run）")
    p.add_argument("--remote-base", help="远端基地址，例 git@github-zjashanda:zjashanda")
    p.add_argument("--out")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fail-on-drift", action="store_true")
    p.add_argument("--fail-on-remote", action="store_true")
    p.set_defaults(func=cmd_apply)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
