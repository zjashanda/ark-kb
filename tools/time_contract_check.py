#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨仓库时间契约交叉验证。

两类证据：

1. ``--samples``（默认执行）：把同一组时间样例分别喂给各仓库的 time lint /
   契约校验函数，检查每个仓库对同一字符串给出**一致结论**。
2. ``--matrix``：用每个仓库自己的 lint 扫描其他仓库的源码树，检查是否出现
   「A 仓库的 lint 判定 B 仓库的产物违规」这类跨仓库冲突。

契约基准（裁决前）：``YYYY-MM-DD HH:MM:SS``，北京时间，无时区后缀、无毫秒。
``venusahisiburner`` 目前仍是 ``YYYY-MM-DDThh:mm:ss.sss``，属于待
郑保山裁决的 A/B 项；用 ``--allow-pending-legacy`` 把它标为
``PENDING`` 而不是 ``FAIL``。

用法::

    python3 tools/time_contract_check.py                 # 样例一致性 + 路径矩阵
    python3 tools/time_contract_check.py --repos ../     # 指定同级仓库根目录
    python3 tools/time_contract_check.py --json          # 机器可读输出
    python3 tools/time_contract_check.py --only samples  # 只跑样例一致性
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve()
DEFAULT_REPOS_ROOT = HERE.parents[2]

CONTRACT_TEXT = "YYYY-MM-DD HH:MM:SS"
CONTRACT_EXAMPLE = "2026-11-10 14:05:00"

#: 样例 -> 期望结论（True=合规）
SAMPLES: List[Tuple[str, str, bool]] = [
    ("contract_text", CONTRACT_EXAMPLE, True),
    ("t_separator", "2026-11-10T14:05:00", False),
    ("t_millis", "2026-11-10T14:05:00.123", False),
    ("utc_suffix", "2026-11-10 14:05:00Z", False),
    ("offset_suffix", "2026-11-10 14:05:00+08:00", False),
    ("space_millis", "2026-11-10 14:05:00.123", False),
]


@dataclass(frozen=True)
class Lint:
    """一个仓库的时间 lint 适配器。"""

    repo: str
    #: 支持任意路径扫描的 lint：命令模板里的 {target} 会被替换
    path_cmd: Optional[Sequence[str]] = None
    #: 只接受单个时间字符串的校验命令，参数追加在末尾
    value_cmd: Optional[Sequence[str]] = None

    def supports_paths(self) -> bool:
        return self.path_cmd is not None

    def supports_values(self) -> bool:
        return self.value_cmd is not None


LINTS: List[Lint] = [
    Lint("ark-node", path_cmd=("python3", "tools/time_lint.py", "--json", "{target}")),
    Lint("device-io", path_cmd=("python3", "tools/time_lint.py", "{target}")),
    Lint(
        "tts-runtime",
        path_cmd=("python3", "tools/time_lint.py", "--root", "{target}", "--json"),
    ),
    Lint(
        "skillhub-sync",
        path_cmd=("python3", "tools/time_lint.py", "--root", "{target}", "--json"),
    ),
    Lint("ark-archive", value_cmd=("python3", "lib/ark_time.py", "check")),
    Lint(
        "venusahisiburner",
        value_cmd=(
            "python3",
            "-c",
            "import sys;from scripts.core.contract import is_bj_timestamp;"
            "sys.exit(0 if is_bj_timestamp(sys.argv[1]) else 1)",
        ),
    ),
]

#: 只能扫自己仓库、或没有独立 lint 的仓库，仅作说明
NOTES = {
    "audio-runtime": "lint 只扫自身仓库根，不支持外部路径；已纳入 --matrix 的扫描目标",
    "asset-tools": "无 tools/time_lint.py；时间格式由 util.py 常量约束，需人工比对",
}


def _run(cmd: Sequence[str], cwd: Path) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - 环境问题
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _repo_path(root: Path, name: str) -> Optional[Path]:
    path = root / name
    return path if path.is_dir() else None


SAMPLE_EXTS = ("py", "json", "md")


def _write_sample_files(tmp: Path) -> Dict[str, List[str]]:
    """把每个样例写成多种扩展名的文件，返回 样例名 -> 文件名列表。"""

    names: Dict[str, List[str]] = {}
    for name, value, _expected in SAMPLES:
        names[name] = []
        for ext in SAMPLE_EXTS:
            filename = "{0}.{1}".format(name, ext)
            if ext == "json":
                body = json.dumps({"timestamp": value}, ensure_ascii=False)
            elif ext == "md":
                body = "# 样例\n\n时间: {0}\n".format(value)
            else:
                body = "# 时间样例: {0}\n".format(value)
            (tmp / filename).write_text(body, encoding="utf-8")
            names[name].append(filename)
    return names


def _path_sample_verdicts(
    lint: Lint, repo_dir: Path
) -> Tuple[Dict[str, Optional[bool]], Dict[str, str]]:
    """用仓库自带的 lint 扫描样例目录，判断每个样例是否被判违规。

    返回 样例名 -> True(合规)/False(违规)/None(该 lint 没检查这个文件)。
    """

    verdicts: Dict[str, Optional[bool]] = {name: None for name, _v, _e in SAMPLES}
    detail: Dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="time-samples-") as tmp_name:
        tmp = Path(tmp_name)
        names = _write_sample_files(tmp)
        cmd = [part.replace("{target}", str(tmp)) for part in lint.path_cmd or ()]
        code, output = _run(cmd, repo_dir)
        if code not in (0, 1):
            for name in verdicts:
                detail[name] = "工具错误(exit={0}): {1}".format(code, output.strip()[:200])
            return verdicts, detail
        lowered = output.lower()
        for name, files in names.items():
            hit = any(filename.lower() in lowered for filename in files)
            if hit:
                verdicts[name] = False
            else:
                # 没有任何一条输出提到样例文件：要么 lint 全放行，要么它没扫这些文件。
                verdicts[name] = True
    return verdicts, detail


def check_samples(root: Path, allow_pending_legacy: bool) -> List[Dict[str, object]]:
    """每个仓库对同一批样例给出结论，返回逐仓库明细。"""

    rows: List[Dict[str, object]] = []
    for lint in LINTS:
        repo_dir = _repo_path(root, lint.repo)
        if repo_dir is None:
            rows.append({"repo": lint.repo, "status": "SKIP", "reason": "未找到本地检出"})
            continue
        if not lint.supports_values() and not lint.supports_paths():
            rows.append({"repo": lint.repo, "status": "SKIP", "reason": "无校验入口"})
            continue

        verdicts: Dict[str, Optional[bool]] = {}
        detail: Dict[str, str] = {}
        if lint.supports_values():
            for name, value, _expected in SAMPLES:
                cmd = list(lint.value_cmd or ()) + [value]
                code, output = _run(cmd, repo_dir)
                if code == 127:
                    verdicts[name] = None
                    detail[name] = "执行失败: " + output.strip()[:200]
                    continue
                # 0/1 才算得出结论；2 视为工具错误
                if code not in (0, 1):
                    verdicts[name] = None
                    detail[name] = "工具错误(exit={0}): {1}".format(code, output.strip()[:200])
                    continue
                verdicts[name] = code == 0
        else:
            verdicts, detail = _path_sample_verdicts(lint, repo_dir)
            if all(value is None for value in verdicts.values()):
                rows.append(
                    {
                        "repo": lint.repo,
                        "status": "SKIP",
                        "reason": "lint 未覆盖样例文件: " + "; ".join(list(detail.values())[:1]),
                    }
                )
                continue

        mismatches: List[str] = []
        pending: List[str] = []
        for name, _value, expected in SAMPLES:
            got = verdicts[name]
            if got == expected:
                continue
            if (
                allow_pending_legacy
                and lint.repo == "venusahisiburner"
                and name in ("t_millis", "t_separator")
                and got
            ):
                pending.append(name)
                continue
            mismatches.append("{0}: 期望 {1} 实得 {2}".format(name, expected, got))

        status = "PASS" if not mismatches else "FAIL"
        if status == "PASS" and pending:
            status = "PENDING"
        rows.append(
            {
                "repo": lint.repo,
                "status": status,
                "verdicts": verdicts,
                "mismatches": mismatches,
                "pending": pending,
                "detail": detail,
            }
        )
    return rows


def _count_from_json(output: str) -> Optional[int]:
    """从 lint 的 JSON 输出里取违规数；拿不到返回 None。"""

    start = output.find("{")
    while start != -1:
        try:
            data = json.loads(output[start:])
        except json.JSONDecodeError:
            start = output.find("{", start + 1)
            continue
        if isinstance(data, dict):
            if isinstance(data.get("count"), int):
                return int(data["count"])
            if isinstance(data.get("violations"), list):
                return len(data["violations"])
        return None
    return None


def check_matrix(root: Path, targets: Sequence[str]) -> List[Dict[str, object]]:
    """用每个 lint 扫描每个目标仓库，记录违规数。"""

    rows: List[Dict[str, object]] = []
    for lint in LINTS:
        if not lint.supports_paths():
            continue
        lint_dir = _repo_path(root, lint.repo)
        if lint_dir is None:
            rows.append({"lint": lint.repo, "status": "SKIP", "reason": "未找到本地检出"})
            continue
        for target in targets:
            target_dir = _repo_path(root, target)
            if target_dir is None:
                continue
            cmd = [part.replace("{target}", str(target_dir)) for part in lint.path_cmd or ()]
            code, output = _run(cmd, lint_dir)
            if code == 127:
                rows.append(
                    {"lint": lint.repo, "target": target, "status": "ERROR", "reason": output[:200]}
                )
                continue
            if code not in (0, 1):
                rows.append(
                    {
                        "lint": lint.repo,
                        "target": target,
                        "status": "ERROR",
                        "exit": code,
                        "reason": output.strip()[:200],
                    }
                )
                continue
            rows.append(
                {
                    "lint": lint.repo,
                    "target": target,
                    "status": "CLEAN" if code == 0 else "VIOLATIONS",
                    "exit": code,
                    "count": _count_from_json(output),
                }
            )
    return rows


def _print_samples(rows: Sequence[Dict[str, object]]) -> None:
    print("== 样例一致性（契约 {0}，例 {1}）==".format(CONTRACT_TEXT, CONTRACT_EXAMPLE))
    for row in rows:
        line = "{0:<20} {1}".format(row["repo"], row["status"])
        if row.get("reason"):
            line += "  " + str(row["reason"])
        print(line)
        for item in row.get("mismatches", []) or []:
            print("    - " + str(item))
        for item in row.get("pending", []) or []:
            print("    ~ 待裁决放行: " + str(item))


def _print_matrix(rows: Sequence[Dict[str, object]]) -> None:
    print("== 跨仓库扫描矩阵 ==")
    for row in rows:
        if "target" in row:
            count = row.get("count")
            suffix = "" if count is None else " ({0} 处)".format(count)
            print(
                "{0:<16} -> {1:<18} {2}{3}".format(
                    row["lint"], row["target"], row["status"], suffix
                )
            )
        else:
            print("{0:<16} {1}  {2}".format(row["lint"], row["status"], row.get("reason", "")))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="跨仓库时间契约交叉验证")
    parser.add_argument(
        "--repos",
        default=str(DEFAULT_REPOS_ROOT),
        help="同级仓库根目录（默认 ark-kb 的上一级）",
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument(
        "--only",
        choices=("samples", "matrix", "all"),
        default="all",
        help="只跑某一部分",
    )
    parser.add_argument(
        "--allow-pending-legacy",
        action="store_true",
        help="把 venusahisiburner 的 T+毫秒标记为待裁决(PENDING)而非 FAIL",
    )
    parser.add_argument(
        "--targets",
        default="ark-node,device-io,tts-runtime,audio-runtime,skillhub-sync,ark-archive,lstest",
        help="--matrix 的扫描目标，逗号分隔",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.repos).resolve()
    if not root.is_dir():
        print("repos root not found: {0}".format(root), file=sys.stderr)
        return 2

    samples = (
        check_samples(root, args.allow_pending_legacy)
        if args.only in ("samples", "all")
        else []
    )
    matrix = (
        check_matrix(root, [item.strip() for item in args.targets.split(",") if item.strip()])
        if args.only in ("matrix", "all")
        else []
    )

    failed = [row for row in samples if row.get("status") == "FAIL"]
    failed += [row for row in matrix if row.get("status") == "ERROR"]

    if args.json:
        payload = {
            "contract": {"text": CONTRACT_TEXT, "example": CONTRACT_EXAMPLE},
            "repos_root": str(root),
            "samples": samples,
            "matrix": matrix,
            "notes": NOTES,
            "ok": not failed,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if samples:
            _print_samples(samples)
        if matrix:
            print()
            _print_matrix(matrix)
        if NOTES:
            print()
            print("== 说明 ==")
            for name, text in NOTES.items():
                print("{0:<16} {1}".format(name, text))

    if failed:
        print("\n结论: FAIL（{0} 项不一致）".format(len(failed)), file=sys.stderr)
        return 1
    print("\n结论: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
