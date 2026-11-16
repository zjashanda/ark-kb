"""知识前置检查与降级策略（Stage 2 演练产物，候选并入 ark-kb）。

把 ark-kb 文档里的降级矩阵变成可执行判定，避免每个 Agent 各写一份：

    freshness=fresh + 服务可用      -> PROCEED（记 knowledge_snapshot）
    freshness=stale   + 普通任务     -> PROCEED_WITH_CACHE（回执必须写 freshness=stale + commit）
    freshness=stale   + 高风险任务    -> BLOCKED_KB_STALE
    服务不可用        + 普通任务     -> PROCEED_WITH_CACHE（未过期）否则 GIT_FALLBACK
    服务不可用        + 高风险任务    -> BLOCKED_KB_UNAVAILABLE
    freshness=unknown + 任意         -> 按不可用处理（没有成功同步记录 = 不可信）

用法：
    python3 kb_policy.py --freshness fresh --risk high --json
    python3 kb_policy.py --selftest            # 跑判定矩阵自检
"""

from __future__ import annotations

import argparse
import json
import sys

RISKS = ("normal", "high")
FRESHNESS = ("fresh", "stale", "unknown", "unavailable")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def evaluate(*, risk: str, freshness: str, cache: dict | None = None,
             snapshot: dict | None = None) -> dict:
    """返回 {decision, reason, receipt_required, snapshot}。

    cache: {"entry_ids": [...], "source_commit": "...", "recorded_at": "...",
            "age_seconds": int, "max_age_seconds": int}
    """
    if risk not in RISKS:
        raise ValueError(f"risk 只能是 {RISKS}")
    if freshness not in FRESHNESS:
        raise ValueError(f"freshness 只能是 {FRESHNESS}")

    cache = cache or {}
    usable_cache = bool(cache.get("entry_ids")) and int(cache.get("age_seconds", 10 ** 9)) <= int(
        cache.get("max_age_seconds", 0)
    )
    base = {
        "risk": risk,
        "freshness": freshness,
        "cache_usable": usable_cache,
        "snapshot": snapshot,
    }

    if freshness == "fresh":
        return {**base, "decision": "PROCEED", "reason": "服务 fresh，按快照执行",
                "receipt_required": ["knowledge_snapshot"]}

    if freshness == "stale":
        if risk == "high":
            return {**base, "decision": "BLOCKED_KB_STALE",
                    "reason": "高风险任务不接受落后索引；先同步或等索引跟上",
                    "receipt_required": ["blocked_code", "source_commit", "indexed_commit"]}
        if usable_cache:
            return {**base, "decision": "PROCEED_WITH_CACHE",
                    "reason": "普通任务可用未过期缓存，回执必须写明 freshness=stale 与所用提交",
                    "receipt_required": ["knowledge_snapshot", "freshness=stale", "source_commit"]}
        return {**base, "decision": "GIT_FALLBACK",
                "reason": "缓存过期且索引落后：只读 clone/pull ark-kb 后跑 tools/kb.py query",
                "receipt_required": ["knowledge_snapshot", "freshness=stale", "fallback=git"]}

    # unknown / unavailable
    if risk == "high":
        return {**base, "decision": "BLOCKED_KB_UNAVAILABLE",
                "reason": "高风险任务在知识服务不可用时不开工",
                "receipt_required": ["blocked_code", "cache_age_seconds"]}
    if usable_cache:
        return {**base, "decision": "PROCEED_WITH_CACHE",
                "reason": "知识服务不可用，用未过期缓存；回执写明 KB 不可用与缓存时间",
                "receipt_required": ["knowledge_snapshot", "kb_unavailable=true", "cache_recorded_at"]}
    return {**base, "decision": "GIT_FALLBACK",
            "reason": "无可用缓存：clone/pull ark-kb 后本地检索",
            "receipt_required": ["knowledge_snapshot", "kb_unavailable=true", "fallback=git"]}


def build_preflight(*, task: str, freshness: str, source_commit: str, indexed_commit: str,
                    entries: list[dict], recorded_at: str) -> dict:
    """把命中条目变成同类任务可直接粘贴的前置检查。"""
    checks = []
    for entry in entries:
        checks.append({
            "entry_id": entry.get("id"),
            "status": entry.get("status"),
            "title": entry.get("title"),
            "must_read": entry.get("claim"),
            "evidence_refs": [item.get("ref") for item in entry.get("evidence") or []],
        })
    return {
        "schema": "ark.knowledge-preflight.v1",
        "task": task,
        "knowledge_snapshot": {
            "source_commit": source_commit,
            "indexed_commit": indexed_commit,
            "freshness": freshness,
            "entry_ids": [entry.get("id") for entry in entries],
            "recorded_at": recorded_at,
        },
        "checks": checks,
    }


def render_markdown(preflight: dict) -> str:
    snap = preflight["knowledge_snapshot"]
    lines = [
        f"# 知识前置检查 · {preflight['task']}",
        "",
        f"- 快照：`source_commit={snap['source_commit']}` / `indexed_commit={snap['indexed_commit']}`"
        f" / freshness=`{snap['freshness']}` / recorded_at={snap['recorded_at']}",
        f"- 命中条目：{', '.join(f'`{item}`' for item in snap['entry_ids']) or '无'}",
        "",
    ]
    for check in preflight["checks"]:
        lines += [
            f"## {check['title']}",
            f"- 条目：`{check['entry_id']}`（{check['status']}）",
            f"- 结论：{check['must_read']}",
            f"- 证据：{', '.join(str(ref) for ref in check['evidence_refs'])}",
            "",
        ]
    return "\n".join(lines)


def selftest() -> int:
    cache_ok = {"entry_ids": ["kb-method-x"], "source_commit": "abc", "recorded_at": "2026-11-16 18:30:00",
                "age_seconds": 60, "max_age_seconds": 3600}
    cache_old = {"entry_ids": ["kb-method-x"], "source_commit": "abc", "recorded_at": "2026-11-01 00:00:00",
                 "age_seconds": 999999, "max_age_seconds": 3600}
    cases = [
        ("fresh", "high", None, "PROCEED"),
        ("fresh", "normal", None, "PROCEED"),
        ("stale", "high", cache_ok, "BLOCKED_KB_STALE"),
        ("stale", "normal", cache_ok, "PROCEED_WITH_CACHE"),
        ("stale", "normal", cache_old, "GIT_FALLBACK"),
        ("unavailable", "high", cache_ok, "BLOCKED_KB_UNAVAILABLE"),
        ("unavailable", "normal", cache_ok, "PROCEED_WITH_CACHE"),
        ("unavailable", "normal", None, "GIT_FALLBACK"),
        ("unknown", "high", cache_ok, "BLOCKED_KB_UNAVAILABLE"),
        ("unknown", "normal", cache_old, "GIT_FALLBACK"),
    ]
    failed = 0
    for freshness, risk, cache, expected in cases:
        got = evaluate(risk=risk, freshness=freshness, cache=cache)["decision"]
        ok = got == expected
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} freshness={freshness} risk={risk} -> {got} (期望 {expected})")
    print(f"\n矩阵 {len(cases) - failed}/{len(cases)} PASS")
    return EXIT_OK if not failed else EXIT_FAIL


def main() -> int:
    parser = argparse.ArgumentParser(description="知识前置检查与降级策略")
    parser.add_argument("--risk", choices=RISKS)
    parser.add_argument("--freshness", choices=FRESHNESS)
    parser.add_argument("--cache", help="缓存快照 JSON 文件")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.risk or not args.freshness:
        parser.error("需要 --risk 与 --freshness（或 --selftest）")
    cache = None
    if args.cache:
        with open(args.cache, encoding="utf-8") as handle:
            cache = json.load(handle)
    result = evaluate(risk=args.risk, freshness=args.freshness, cache=cache)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['decision']}｜{result['reason']}")
    return EXIT_OK if not result["decision"].startswith("BLOCKED") else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
