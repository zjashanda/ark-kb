#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ark_receipt.py —— 由归档 manifest 生成 run.receipt.v1 回执。

设计要点
--------
1. 回执事实来源是**归档后**的 manifest.json（其 sha256 已在存储服务器上重算校验过），
   不是跑测机上的临时目录，所以 evidence_dir 一定写成存储路径。
2. 只读本地文件，不做网络访问；取/传由 ark-receipt.sh、ark-receipt.ps1 负责。
3. 输出除 schema/receipt.v1.json 的必填字段外，额外带 `evidence_files`（path+sha256），
   供 ark-kb 的 kb.py 在「证据不在本机」时仍然登记每个文件的存储路径。

用法
----
    ark_receipt.py --manifest <dir>/manifest.json --summary <dir>/summary_final.json \
        --node win009 --project tcl-r5 [--run-id 20261102_090644_wake_recognition] \
        [--task "…"] [--skill lstest] [--skill-version 0.1] [--firmware …] \
        [--lessons lessons.json] [--bugs bugs.json] [--out run.receipt.json] [--dry-run]

退出码：0 成功；2 输入/校验失败；3 本地哈希与 manifest 不一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "run.receipt.v1"
DEFAULT_STORAGE_ROOT = "/srv/storage/ark"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RESULT_MAP = {
    "PASS": "pass",
    "FAIL": "fail",
    "BLOCKED": "blocked",
    "INVALID": "invalid",
    "ERROR": "needs_review",
    "NEEDS_REVIEW": "needs_review",
}


def die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        die(f"找不到文件：{path}")
    except json.JSONDecodeError as exc:
        die(f"JSON 解析失败：{path}：{exc}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_rfc3339(value: str, offset: str) -> str:
    """manifest 里的时间是「北京时间、无时区后缀」，补上偏移量后转 RFC3339。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text):
        return text.replace(" ", "T", 1)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            moment = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return moment.strftime("%Y-%m-%dT%H:%M:%S") + offset
    die(f"无法解析时间：{value!r}")


def build_evidence(manifest: dict, evidence_dir: str):
    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        die("manifest.files 为空，无法生成 evidence_sha256")
    hashes: list[str] = []
    evidence_files: list[dict] = []
    total_bytes = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "").replace("\\", "/").strip().lstrip("./")
        sha = str(item.get("sha256") or "").strip().lower()
        size = int(item.get("bytes") or 0)
        if not rel or not SHA_RE.match(sha):
            die(f"manifest 条目非法（path/sha256）：{item!r}")
        hashes.append(sha)
        evidence_files.append({"path": rel, "sha256": sha, "bytes": size})
        total_bytes += size
    if not hashes:
        die("manifest.files 中没有可用条目")
    return {
        "evidence_dir": evidence_dir.rstrip("/"),
        "evidence_sha256": hashes,
        "evidence_files": evidence_files,
        "total_bytes": total_bytes,
    }


def build_totals(summary: dict, manifest_files: int, total_bytes: int) -> dict:
    normal = summary.get("normal_window") or {}
    boundary = summary.get("boundary_window") or {}
    totals = {
        "rounds": summary.get("completed_rounds", 0),
        "target_rounds": summary.get("target_rounds", 0),
        "duration_minutes": summary.get("duration_minutes", 0),
        "recognized": normal.get("recognized", 0),
        "failed": normal.get("failed", 0),
        "recognition_rate": normal.get("recognition_rate", None),
        "boundary_unexpected": boundary.get("unexpected_results", 0),
        "serial_error_kinds": len(summary.get("serial_errors") or {}),
        "warning_markers": sum((summary.get("warning_marker_round_counts") or {}).values()),
        "archived_files": manifest_files,
        "archived_bytes": total_bytes,
    }
    if summary.get("status_counts"):
        totals["status_counts"] = summary["status_counts"]
    return totals


def build_failures(summary: dict) -> list[dict]:
    failures: list[dict] = []
    normal = summary.get("normal_window") or {}
    boundary = summary.get("boundary_window") or {}
    if int(normal.get("failed") or 0) > 0:
        failures.append(
            {
                "name": "唤醒/命令词识别失败",
                "reason": f"正常窗口 {normal.get('failed')} 轮未识别（识别率 {normal.get('recognition_rate')}）",
                "attribution": "device",
                "evidence": ["summary_final.json"],
            }
        )
    if int(boundary.get("unexpected_results") or 0) > 0:
        failures.append(
            {
                "name": "边界窗口出现非预期结果",
                "reason": f"unexpected_results={boundary.get('unexpected_results')}",
                "attribution": "corpus",
                "evidence": ["summary_final.json"],
            }
        )
    if str(summary.get("error") or "").strip():
        failures.append(
            {
                "name": "运行期错误",
                "reason": str(summary["error"]).strip()[:500],
                "attribution": "tool",
                "evidence": ["errors.log", "summary_final.json"],
            }
        )
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="由归档 manifest 生成 run.receipt.v1")
    ap.add_argument("--manifest", required=True, help="归档目录下的 manifest.json")
    ap.add_argument("--summary", default=None, help="归档目录下的 summary_final.json")
    ap.add_argument("--node", default=None, help="节点名（缺省取 manifest.node）")
    ap.add_argument("--project", default=None, help="项目名（缺省取 manifest.project）")
    ap.add_argument("--run-id", default=None, help="run_id（缺省取 manifest.run_id）")
    ap.add_argument("--storage-root", default=DEFAULT_STORAGE_ROOT, help="存储根，默认 /srv/storage/ark")
    ap.add_argument("--evidence-dir", default=None, help="显式指定 evidence_dir（默认自动拼存储路径）")
    ap.add_argument("--task", default=None, help="任务描述，进 KB 标题/claim")
    ap.add_argument("--skill", default="lstest", help="产出该结果的 skill")
    ap.add_argument("--skill-version", default="unknown", help="skill 版本")
    ap.add_argument("--firmware", default=None, help="固件标识")
    ap.add_argument("--platform", default=None, help="平台描述，默认 '<node> (<manifest.device>)'")
    ap.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    ap.add_argument("--lessons", default=None, help="lessons JSON 文件（数组）")
    ap.add_argument("--bugs", default=None, help="bugs_found JSON 文件（数组）")
    ap.add_argument("--tags", default=None, help="逗号分隔附加标签")
    ap.add_argument("--tz-offset", default="+08:00", help="无时区时间补的偏移，默认 +08:00")
    ap.add_argument("--out", default=None, help="回执输出路径（缺省与 manifest 同目录）")
    ap.add_argument("--no-local-verify", action="store_true", help="跳过本地哈希复核")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).expanduser()
    manifest = load_json(manifest_path)
    base_dir = manifest_path.parent
    summary_path = Path(args.summary).expanduser() if args.summary else (base_dir / "summary_final.json")
    summary = load_json(summary_path) if summary_path.exists() else {}

    run_id = (args.run_id or manifest.get("run_id") or "").strip()
    node = (args.node or manifest.get("node") or "").strip()
    project = (args.project or manifest.get("project") or "").strip()
    if not run_id or not node or not project:
        die("run_id / node / project 必须可知（manifest 或命令行给出）")

    evidence_dir = args.evidence_dir or f"{args.storage_root.rstrip('/')}/results/{node}/{project}/{run_id}"

    # 同一份 manifest 若就在本机，顺手复核哈希，早失败早发现
    verify_line = "VERIFY: skipped"
    if not args.no_local_verify:
        checked = mismatched = 0
        for item in manifest.get("files") or []:
            rel = str(item.get("path") or "").replace("\\", "/").strip().lstrip("./")
            local = base_dir / rel
            if not rel or not local.is_file():
                continue
            checked += 1
            if sha256_file(local) != str(item.get("sha256") or "").lower():
                mismatched += 1
        verify_line = f"VERIFY: local_files={checked}/{len(manifest.get('files') or [])} mismatches={mismatched}"
        if mismatched:
            print(verify_line)
            die(f"本地文件与 manifest 哈希不一致 {mismatched} 个，拒绝生成回执", 3)

    evidence = build_evidence(manifest, evidence_dir)
    totals = build_totals(summary, len(evidence["evidence_files"]), evidence["total_bytes"])

    raw_result = str(manifest.get("result") or "").strip().upper()
    result = RESULT_MAP.get(raw_result)
    if result is None:
        die(f"manifest.result={raw_result!r} 无法映射到 pass/fail/blocked/invalid/needs_review")

    started = to_rfc3339(manifest.get("started_at"), args.tz_offset)
    ended = to_rfc3339(manifest.get("ended_at") or manifest.get("archived_at"), args.tz_offset)
    if not started or not ended:
        die("manifest 缺少 started_at / ended_at")

    task = (args.task or f"{project} 压测归档（{run_id}）").strip()
    platform = args.platform or f"{node} ({manifest.get('device') or 'unknown'})"

    lessons = load_json(Path(args.lessons).expanduser()) if args.lessons else []
    bugs = load_json(Path(args.bugs).expanduser()) if args.bugs else []
    if not isinstance(lessons, list) or not isinstance(bugs, list):
        die("--lessons / --bugs 必须是 JSON 数组")

    if args.confidence:
        confidence = args.confidence
    elif result == "pass" and totals.get("rounds", 0) and totals.get("failed", 0) == 0:
        confidence = "high"
    else:
        confidence = "medium"

    tags = ["archive", node, project, result]
    if args.tags:
        tags += [part.strip() for part in args.tags.split(",") if part.strip()]

    receipt = {
        "schema": SCHEMA,
        "run_id": run_id,
        "task": task,
        "skill": args.skill,
        "skill_version": args.skill_version,
        "scope": {
            "device": manifest.get("device"),
            "project": project,
            "firmware": args.firmware,
            "platform": platform,
        },
        "result": result,
        "totals": totals,
        "failures": build_failures(summary),
        "bugs_found": bugs,
        "evidence_dir": evidence["evidence_dir"],
        "evidence_sha256": evidence["evidence_sha256"],
        "evidence_files": evidence["evidence_files"],
        "lessons": lessons,
        "confidence": confidence,
        "started_at": started,
        "ended_at": ended,
        "notes": (
            f"回执由归档 manifest 自动生成：node={node} project={project} "
            f"archived_at={manifest.get('archived_at')} files={len(evidence['evidence_files'])} "
            f"bytes={evidence['total_bytes']}；源目录 {manifest.get('source_dir')}"
        ),
        "tags": sorted(set(tags)),
        "archive": {
            "node": node,
            "project": project,
            "storage_root": args.storage_root.rstrip("/"),
            "archived_at": manifest.get("archived_at"),
            "source_dir": manifest.get("source_dir"),
            "manifest_sha256": sha256_file(manifest_path),
        },
    }

    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    out_path = Path(args.out).expanduser() if args.out else (base_dir / "run.receipt.json")
    if args.dry_run:
        print(verify_line)
        print(payload, end="")
        print(f"DRY-RUN: receipt 未落盘（目标 {out_path}）", file=sys.stderr)
        return 0

    out_path.write_text(payload, encoding="utf-8")
    print(verify_line)
    print(f"RECEIPT: {out_path}")
    print(f"RECEIPT_SHA256: {sha256_file(out_path)}")
    print(f"EVIDENCE_DIR: {evidence['evidence_dir']}")
    print(f"EVIDENCE_FILES: {len(evidence['evidence_files'])} BYTES: {evidence['total_bytes']}")
    print(f"RESULT: {result}  CONFIDENCE: {confidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
