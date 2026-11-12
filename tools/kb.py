#!/usr/bin/env python3
"""ark-kb 知识库入口。

    kb.py record --receipt <path>     回执归一成条目（pending），更新索引
    kb.py checkpoint --event <path>   生命周期事件校验后追加到 append-only WAL
    kb.py outbox --replay             查看/恢复检查点 outbox 状态
    kb.py promote                     扫描跨项目提升候选（只读）
    kb.py query  --device X ...       检索摘要 + 证据引用，不返回全文
    kb.py query-back --delivery X     回查新条目是否可检索，写回 delivery 回执
    kb.py lint                        校验 schema、证据、重复 id、索引、凭据
    kb.py sync                        拉取远端；--push 只允许推功能分支
    kb.py index                       重建索引（record 会自动调用）

设计口径见 README.md 与 schema/*.json。所有命令离线可跑（sync 除外）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:  # 作为脚本运行与作为模块导入都能拿到适配层
    import secret_scan
except ImportError:  # pragma: no cover - 仅在非常规导入路径下触发
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import secret_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY_TYPES = ("knowledge", "method", "run", "bug")
STATUSES = ("pending", "active", "stale", "superseded")
CONFIDENCES = ("high", "medium", "low")
RESULTS = ("pass", "fail", "blocked", "invalid", "needs_review")
EVIDENCE_KINDS = ("run", "file", "commit", "issue", "url")

STALE_DAYS = 90
MERGE_RATIO = 0.86
EXIT_FAIL = 3
EXIT_INCOMPLETE = 1
INDEX_NAMES = ("by-device", "by-capability", "by-skill")

# 知识同步契约（NOAH-66）：读侧留痕 + 写侧回流回执
DELIVERY_SCHEMA = "ark.delivery.v1"
NO_KB_FIXED_REASONS = ("no-new-knowledge", "pure-inventory", "sensitive-not-indexable")
DUPLICATE_REASON_PREFIX = "duplicate-of-existing:"
BEIJING = timezone(timedelta(hours=8))
TEXT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 事件驱动回流（v2）：检查点先落 append-only WAL，再异步归档入库
CHECKPOINT_TRIGGERS = (
    "EXECUTION_CHECK", "STAGE_FINISHED", "FINAL_RECEIPT",
    "BLOCKED", "FAIL", "NEEDS_REVIEW",
    "WATCHDOG_RUNNING_NO_EVIDENCE", "WATCHDOG_STATE_DRIFT",
    "WATCHDOG_TIMEOUT", "WATCHDOG_HEARTBEAT_LOST",
    "MANUAL_CANCEL", "RUNTIME_CRASH", "RECOVERY_REPLAY",
)
CHECKPOINT_QUALITIES = ("formal", "candidate", "evidence_gap")
SCOPE_LEVELS = ("global", "capability", "platform", "device_family", "project", "node", "run")
OUTBOX_STATUSES = ("pending", "archived", "ingested", "failed", "all")
PROJECT_TAG_PREFIX = "project:"
GENERIC_PROJECTS = ("通用", "general", "common")


class KBError(RuntimeError):
    """可预期失败：由 main() 转成退出码 3，不打堆栈。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")  # noqa: time-lint  # time-lint:allow


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)  # noqa: time-lint  # time-lint:allow
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # noqa: time-lint  # time-lint:allow
    return parsed


def now_bj_text() -> str:
    """北京时间文本（空格分隔、秒精度、无时区标记），同步契约字段一律用它。"""
    return datetime.now(BEIJING).strftime(TEXT_TIME_FORMAT)


def valid_no_kb_reason(value: str | None) -> bool:
    """NO_KB_REQUIRED 的理由必须落在封闭集合内，禁止静默跳过。"""
    text = (value or "").strip()
    if text in NO_KB_FIXED_REASONS:
        return True
    if text.startswith(DUPLICATE_REASON_PREFIX):
        return bool(text[len(DUPLICATE_REASON_PREFIX):].strip())
    return False


def idempotency_key(scope: dict, run_id: str) -> str:
    """幂等键 = sha256(scope + run_id)；同一 run 重放不新增条目。"""
    material = json.dumps(scope if isinstance(scope, dict) else {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{material}|{run_id}".encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm_text(value) -> str:
    text = unicodedata.normalize("NFKC", "" if value is None else str(value)).lower()
    return re.sub(r"[\s，。、；：！？,.;:!?/\\|()（）\[\]【】<>《》\"'`~_\-+*=]+", "", text)


CAPABILITY_ALIASES: dict[str, tuple[str, ...]] = {
    "wake-recognition": ("唤醒", "唤醒识别", "wake", "唤醒率", "识别"),
    "asr": ("识别", "离在线识别", "语音识别"),
    "tts": ("合成", "播报", "语音合成", "index-tts", "indextts"),
    "playback": ("播放", "声卡", "播放器"),
    "recording": ("录音", "采集", "麦克风"),
    "burn": ("烧录", "刷机", "固件烧录"),
    "ota": ("ota", "升级", "断电压测", "掉电"),
    "reset": ("复位", "上下电", "断电", "电源"),
    "serial": ("串口", "日志", "串口日志"),
    "watchdog": ("看门狗", "挂死", "止损", "超时判定"),
    "crash": ("崩溃", "exception", "重启", "死机"),
    "stress": ("压测", "长稳", "稳定性", "mtbf"),
}


def capability_slugs(*texts) -> list[str]:
    """从文本里识别能力名，返回受控词表里的英文 slug（用于 tags）。"""
    blob = " ".join(str(t) for t in texts if t).lower()
    found: list[str] = []
    for slug, words in CAPABILITY_ALIASES.items():
        for word in words:
            if word in blob:
                found.append(slug)
                break
    return found


def expand_capability(needle: str) -> set[str]:
    """查询词 -> 归一化候选集合（含中英别名双向展开）。"""
    base = norm_text(needle)
    out = {base}
    for slug, words in CAPABILITY_ALIASES.items():
        pool = {slug, *words}
        if any(norm_text(item) == base for item in pool):
            out.update(norm_text(item) for item in pool)
    return {item for item in out if len(item) >= 2}


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    parts = re.split(r"[^0-9a-z\u4e00-\u9fff]+", text)
    return [part for part in parts if len(part) >= 2]


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KBError(f"读不到 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise KBError(f"{path} 不是合法 JSON: {exc}") from exc


# --------------------------------------------------------------------------- #
# 回流回执 ark.delivery.v1（读改写，绝不删除未知字段）
# --------------------------------------------------------------------------- #

def load_delivery(path: Path) -> dict | None:
    if not path.is_file():
        return None
    data = read_json(path)
    if not isinstance(data, dict):
        raise KBError(f"{path} 不是 ark.delivery.v1 对象")
    return data


def write_delivery(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def delivery_defaults(run_id: str, scope: dict) -> dict:
    return {
        "schema": DELIVERY_SCHEMA,
        "run_id": run_id,
        "idempotency_key": idempotency_key(scope, run_id),
        "archive_status": "pending",
        "kb_ingest_status": "pending",
        "kb_entry_ids": [],
        "kb_query_back_status": "pending",
        "retry": {"attempts": 0, "last_error": ""},
        "updated_at": now_bj_text(),
    }


def ensure_delivery(path: Path, run_id: str, scope: dict) -> dict:
    """已有回执只补齐缺失项；已有值与未知字段原样保留，避免覆盖上游写入。"""
    data = load_delivery(path) or {}
    for key, value in delivery_defaults(run_id, scope).items():
        data.setdefault(key, value)
    data["schema"] = DELIVERY_SCHEMA
    data["run_id"] = run_id
    retry = data.get("retry") if isinstance(data.get("retry"), dict) else {}
    data["retry"] = {**retry, "attempts": int(retry.get("attempts") or 0),
                     "last_error": str(retry.get("last_error") or "")}
    data["updated_at"] = now_bj_text()
    write_delivery(path, data)
    return data


def update_delivery(path: Path, fields: dict) -> dict:
    data = load_delivery(path) or {}
    data.update(fields)
    data["updated_at"] = now_bj_text()
    write_delivery(path, data)
    return data


# --------------------------------------------------------------------------- #
# JSON Schema 子集校验（不引入第三方依赖，离线可跑）
# --------------------------------------------------------------------------- #

def _type_ok(value, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _resolve_ref(root_schema: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise KBError(f"不支持外部 $ref: {ref}")
    node = root_schema
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise KBError(f"$ref 无法解析: {ref}")
        node = node[part]
    return node


def validate(value, schema: dict, root_schema: dict | None = None, path: str = "$") -> list[str]:
    root_schema = root_schema or schema
    errors: list[str] = []

    if "$ref" in schema:
        return validate(value, _resolve_ref(root_schema, schema["$ref"]), root_schema, path)

    expected = schema.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, option) for option in options):
            errors.append(f"{path}: 类型应为 {expected}，实际 {type(value).__name__}")
            return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 取值 {value!r} 不在允许集合 {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度不足 {schema['minLength']}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            errors.append(f"{path}: 不匹配模式 {pattern}")
        if schema.get("format") == "date-time":
            try:
                parse_time(value)
            except ValueError:
                errors.append(f"{path}: 不是合法 ISO-8601 时间：{value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 小于最小值 {schema['minimum']}")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: 缺少必填字段 {name}")
        properties = schema.get("properties", {})
        for name, sub_schema in properties.items():
            if name in value:
                errors.extend(validate(value[name], sub_schema, root_schema, f"{path}.{name}"))
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}: 出现未定义字段 {name}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: 至少需要 {schema['minItems']} 项")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(validate(item, item_schema, root_schema, f"{path}[{index}]"))
    return errors


def load_schema(root: Path, name: str) -> dict:
    path = root / "schema" / name
    if not path.is_file():
        raise KBError(f"缺少 schema 文件：{path}")
    return read_json(path)


# --------------------------------------------------------------------------- #
# 检查点 WAL 与 outbox（append-only，索引可重建）
# --------------------------------------------------------------------------- #

def evidence_digest(evidence) -> str:
    hashes = sorted(
        str(item.get("sha256"))
        for item in (evidence or [])
        if isinstance(item, dict) and item.get("sha256")
    )
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


def checkpoint_id(event: dict) -> str:
    """幂等键 = sha256(issue_id|run_id|stage|event_seq|evidence_digest)。"""
    material = "|".join([
        str(event.get("issue_id", "")),
        str(event.get("run_id", "")),
        str(event.get("stage", "")),
        str(event.get("event_seq", "")),
        evidence_digest(event.get("evidence")),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def resolve_outbox_dir(root: Path, outbox_arg: str | None) -> Path:
    if not outbox_arg:
        return root / "receipts" / "outbox"
    path = Path(outbox_arg).expanduser()
    return path if path.is_absolute() else (root / path)


def resolve_output_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path)


def wal_files(outbox_dir: Path) -> list[Path]:
    return sorted(outbox_dir.glob("checkpoints-*.jsonl"))


def load_wal_events(outbox_dir: Path) -> list[dict]:
    """WAL 只读：解析所有 checkpoints-*.jsonl，坏行直接报错，绝不改写文件。"""
    events: list[dict] = []
    for path in wal_files(outbox_dir):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise KBError(f"{path.name}:{line_no} 不是合法 JSON: {exc}") from exc
            if isinstance(row, dict):
                events.append(row)
    return events


def outbox_index_path(outbox_dir: Path) -> Path:
    return outbox_dir / "outbox.json"


def load_outbox_index(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("checkpoints"), dict):
        data = data["checkpoints"]
    if not isinstance(data, dict):
        raise KBError(f"{path} 不是 checkpoint_id → 状态的映射")
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_outbox_index(path: Path, index: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def outbox_block(event: dict) -> dict:
    block = dict(event.get("outbox") or {})
    block["trigger"] = event.get("trigger")
    block["at"] = event.get("at")
    block["stage"] = event.get("stage")
    return block


def outbox_closed(block: dict) -> bool:
    """关闭条件：归档 ok + 入库 recorded/skipped_no_kb + 回查 pass/deferred(带原因)。"""
    if block.get("archive_status") != "ok":
        return False
    if block.get("kb_ingest_status") not in ("recorded", "skipped_no_kb"):
        return False
    query_back = block.get("kb_query_back_status")
    if query_back == "pass":
        return True
    retry = block.get("retry") if isinstance(block.get("retry"), dict) else {}
    return query_back == "deferred" and bool(str(retry.get("last_error") or "").strip())


def outbox_state(block: dict) -> str:
    failed = (
        block.get("archive_status") == "failed"
        or block.get("kb_ingest_status") == "failed"
        or block.get("kb_query_back_status") == "fail"
    )
    if failed:
        return "failed"
    if outbox_closed(block):
        return "ingested"
    if block.get("archive_status") == "ok":
        return "archived"
    return "pending"


def outbox_matches(block: dict, status: str) -> bool:
    if status == "all":
        return True
    if status == "archived":
        return block.get("archive_status") == "ok"
    if status == "ingested":
        return block.get("kb_ingest_status") in ("recorded", "skipped_no_kb")
    if status == "failed":
        return outbox_state(block) == "failed"
    return outbox_state(block) == "pending"


def stamp_checkpoint(entry: dict, checkpoint_id_value: str) -> None:
    ids = [str(item) for item in entry.get("checkpoint_ids") or []]
    if checkpoint_id_value not in ids:
        ids.append(checkpoint_id_value)
    entry["checkpoint_ids"] = ids


# --------------------------------------------------------------------------- #
# 存储
# --------------------------------------------------------------------------- #

def resolve_root(root_arg: str | None) -> Path:
    root = Path(root_arg).expanduser().resolve() if root_arg else REPO_ROOT
    if not (root / "schema").is_dir():
        raise KBError(f"{root} 不像知识库根目录（缺少 schema/）")
    return root


def entry_file(root: Path, entry_type: str) -> Path:
    return root / "entries" / entry_type / "entries.jsonl"


def load_entries(root: Path) -> list[dict]:
    entries: list[dict] = []
    for entry_type in ENTRY_TYPES:
        path = entry_file(root, entry_type)
        if not path.is_file():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise KBError(f"{path}:{line_no} 不是合法 JSON: {exc}") from exc
    return entries


def save_entries(root: Path, entries: list[dict]) -> None:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        grouped[entry["type"]].append(entry)
    for entry_type in ENTRY_TYPES:
        path = entry_file(root, entry_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(grouped.get(entry_type, []), key=lambda item: item["id"])
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        path.write_text(text, encoding="utf-8")


def load_registry(root: Path, registry_arg: str | None) -> dict[str, dict] | None:
    candidates = []
    if registry_arg:
        candidates.append(Path(registry_arg).expanduser())
    candidates.extend([root / "registry" / "skills.json", root / "schema" / "registry.skills.json"])
    for path in candidates:
        if path.is_file():
            data = read_json(path)
            items = data if isinstance(data, list) else data.get("skills", [])
            return {item["name"]: item for item in items if isinstance(item, dict) and item.get("name")}
    return None


def scope_key(scope: dict) -> tuple[str, str, str]:
    scope = scope if isinstance(scope, dict) else {}
    return tuple(norm_text(scope.get(key)) for key in ("device", "project", "firmware"))


def entry_id(entry_type: str, scope: dict, title: str, claim: str) -> str:
    seed = "|".join([entry_type, *scope_key(scope), norm_text(title), norm_text(claim)])
    return f"kb-{entry_type}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"


def capability_keys(entry: dict, registry: dict[str, dict] | None, include_registry: bool = True) -> set[str]:
    """能力关键词：条目自身的 tags/项目 + （可选）台账里该 skill 的能力描述。"""
    keys: set[str] = set()
    skill = entry.get("source_skill")
    record = (registry or {}).get(skill) if skill and include_registry else None
    if record:
        for field in ("capability", "hardware", "projects", "layer"):
            value = record.get(field)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item:
                    keys.update(tokenize(str(item)))
        keys.add(norm_text(skill))
    for tag in entry.get("tags") or []:
        keys.add(norm_text(tag))
    scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
    project = scope.get("project")
    if project:
        keys.add(norm_text(project))
    return {key for key in keys if len(key) >= 2}


def build_indexes(entries: list[dict]) -> dict[str, dict[str, list[str]]]:
    """索引只依赖条目自身，不依赖台账，避免台账合并顺序导致索引漂移。"""
    maps: dict[str, dict[str, set[str]]] = {name: defaultdict(set) for name in INDEX_NAMES}
    for entry in entries:
        if entry.get("status") == "superseded":
            continue
        scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
        device = norm_text(scope.get("device"))
        if device:
            maps["by-device"][device].add(entry["id"])
        skill = norm_text(entry.get("source_skill"))
        if skill:
            maps["by-skill"][skill].add(entry["id"])
        for key in capability_keys(entry, None, include_registry=False):
            maps["by-capability"][key].add(entry["id"])
    return {
        name: {key: sorted(ids) for key, ids in sorted(mapping.items()) if ids}
        for name, mapping in maps.items()
    }


def save_indexes(root: Path, entries: list[dict]) -> dict[str, dict[str, list[str]]]:
    maps = build_indexes(entries)
    stamp = now_iso()
    index_dir = root / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    for name in INDEX_NAMES:
        payload = {"schema": "index.v1", "index": name, "generated_at": stamp, "keys": maps[name]}
        (index_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return maps


# --------------------------------------------------------------------------- #
# 回执 → 条目
# --------------------------------------------------------------------------- #

def receipt_evidence(receipt: dict, receipt_path: Path, root: Path, warnings: list[str]) -> list[dict]:
    """证据只登记路径与 sha256；路径优先写成相对知识库根目录，方便别处复核。"""
    evidence_dir_raw = receipt["evidence_dir"]
    evidence_dir = Path(evidence_dir_raw)
    base = evidence_dir if evidence_dir.is_absolute() else (receipt_path.parent / evidence_dir)
    hashes = list(receipt["evidence_sha256"])
    if base.is_dir():
        by_hash: dict[str, Path] = {}
        for path in sorted(base.rglob("*")):
            if path.is_file():
                by_hash.setdefault(sha256_file(path), path)
        missing = [value for value in hashes if value not in by_hash]
        if missing:
            raise KBError(
                "evidence_sha256 与 evidence_dir 内容不匹配，拒绝入库："
                + "、".join(value[:12] + "…" for value in missing)
            )
        items = []
        for value in hashes:
            path = by_hash[value].resolve()
            try:
                ref = path.relative_to(root).as_posix()
            except ValueError:
                ref = f"{evidence_dir_raw.rstrip('/')}/{path.relative_to(base.resolve()).as_posix()}"
            items.append({"kind": "file", "ref": ref, "sha256": value, "verified": True})
        return items
    warnings.append(f"evidence_dir 不在本机（{evidence_dir_raw}），按路径 + sha256 入库，未做文件校验")
    legacy_items = [
        {
            "kind": "run",
            "ref": receipt["run_id"],
            "sha256": value,
            "verified": False,
            "note": "evidence_dir 不在本机，只登记路径与哈希",
        }
        for value in hashes
    ]
    declared = receipt.get("evidence_files")
    if not isinstance(declared, list) or not declared:
        return legacy_items
    # 远端回执自带 evidence_files 时按真实存储路径登记；哈希对不上 evidence_sha256 的条目一律丢弃。
    known_hashes = set(hashes)
    prefix = str(evidence_dir_raw).rstrip("/")
    items: list[dict] = []
    dropped = 0
    for item in declared:
        if not isinstance(item, dict):
            dropped += 1
            continue
        rel = item.get("path")
        digest = item.get("sha256")
        if not isinstance(rel, str) or not rel.strip():
            dropped += 1
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            dropped += 1
            continue
        if digest not in known_hashes:
            dropped += 1
            continue
        items.append(
            {
                "kind": "file",
                "ref": f"{prefix}/{rel.strip().lstrip('/')}",
                "sha256": digest,
                "verified": False,
                "note": "evidence_dir 不在本机，只登记路径与哈希",
            }
        )
    if dropped:
        warnings.append(f"evidence_files 有 {dropped} 项无效或不匹配 evidence_sha256，已忽略")
    return items or legacy_items


def clean_tags(*groups) -> list[str]:
    """收集能力标签并去重排序；空值/非字符串直接丢弃，避免脏 tags 进公开仓库。"""
    tags: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text:
                tags.add(text)
    return sorted(tags)


def new_entry(entry_type: str, scope: dict, title: str, claim: str, evidence: list[dict],
              confidence: str, source_skill: str | None, run_id: str,
              tags: list[str] | None = None) -> dict:
    stamp = now_iso()
    entry = {
        "schema": "entry.v1",
        "id": entry_id(entry_type, scope, title, claim),
        "type": entry_type,
        "scope": {
            "device": scope.get("device"),
            "project": scope.get("project"),
            "firmware": scope.get("firmware"),
            "platform": scope.get("platform"),
        },
        "title": title.strip(),
        "claim": claim.strip(),
        "evidence": evidence,
        "confidence": confidence,
        "status": "pending",
        "superseded_by": None,
        "source_skill": source_skill,
        "created": stamp,
        "updated": stamp,
        "hits": 0,
        "validations": [run_id],
    }
    tags = clean_tags(tags)
    if tags:
        entry["tags"] = tags
    return entry


def evidence_key(item: dict) -> tuple[str, str, str]:
    return item.get("kind", ""), item.get("ref", ""), item.get("sha256", "")


def merge_entry(existing: dict, candidate: dict) -> dict:
    """同 scope 且标题/结论高度相似的条目合并：并证据、并验证次数，必要时升级。"""
    seen = {evidence_key(item) for item in existing.get("evidence", [])}
    for item in candidate.get("evidence", []):
        if evidence_key(item) not in seen:
            existing["evidence"].append(item)
            seen.add(evidence_key(item))
    validations = list(existing.get("validations") or [])
    for run_id in candidate.get("validations") or []:
        if run_id not in validations:
            validations.append(run_id)
    existing["validations"] = validations
    merged_tags = clean_tags(existing.get("tags"), candidate.get("tags"))
    if merged_tags:
        existing["tags"] = merged_tags
    if len(validations) >= 2 and existing["status"] in ("pending", "stale"):
        existing["status"] = "active"
    if existing["status"] == "stale" and len(validations) < 2:
        existing["status"] = "pending"
    rank = {"low": 0, "medium": 1, "high": 2}
    if rank[candidate["confidence"]] > rank[existing["confidence"]]:
        existing["confidence"] = candidate["confidence"]
    existing["updated"] = now_iso()
    return existing


def find_duplicate(entries: list[dict], candidate: dict) -> dict | None:
    target_scope = scope_key(candidate["scope"])
    target_title = norm_text(candidate["title"])
    target_claim = norm_text(candidate["claim"])
    best, best_score = None, 0.0
    for entry in entries:
        if entry["type"] != candidate["type"] or entry["status"] == "superseded":
            continue
        if scope_key(entry["scope"]) != target_scope:
            continue
        entry_title = norm_text(entry["title"])
        entry_claim = norm_text(entry["claim"])
        score = 0.5 * similarity(target_title, entry_title) + 0.5 * similarity(target_claim, entry_claim)
        if score >= MERGE_RATIO and score > best_score:
            best, best_score = entry, score
    return best


def receipt_to_entries(receipt: dict, receipt_path: Path, root: Path, warnings: list[str]) -> list[dict]:
    scope = receipt.get("scope") or {}
    skill = receipt.get("skill")
    evidence = receipt_evidence(receipt, receipt_path, root, warnings)
    run_id = receipt["run_id"]
    totals = receipt.get("totals") or {}
    totals_text = "，".join(f"{key}={value}" for key, value in totals.items()) or "无"
    # 标签是 query --capability 唯一的命中通道：条目自身没有 capability 字段，
    # 英文能力名（如 wake-recognition）必须由回执带下来，否则入库后仍查不到。
    receipt_tags = receipt.get("tags")
    if not receipt_tags:
        derived = capability_slugs(
            receipt.get("task"),
            " ".join(str(item.get("claim", "")) for item in receipt.get("bugs_found") or [] if isinstance(item, dict)),
            " ".join(str(item.get("claim", "")) for item in receipt.get("lessons") or [] if isinstance(item, dict)),
        )
        receipt_tags = [f"capability:{slug}" for slug in derived] or None
    claim = (
        f"{receipt['result'].upper()}｜任务：{receipt['task']}｜"
        f"失败 {len(receipt.get('failures') or [])} 项，缺陷 {len(receipt.get('bugs_found') or [])} 项｜{totals_text}"
    )
    entries = [new_entry("run", scope, f"执行记录：{receipt['task']}", claim, evidence,
                         receipt["confidence"], skill, run_id, tags=receipt_tags)]
    for lesson in receipt.get("lessons") or []:
        entries.append(
            new_entry(
                lesson["type"],
                scope,
                lesson["title"],
                lesson["claim"],
                evidence,
                lesson.get("confidence") or receipt["confidence"],
                skill,
                run_id,
                tags=clean_tags(receipt_tags, lesson.get("tags")),
            )
        )
    for bug in receipt.get("bugs_found") or []:
        entries.append(
            new_entry("bug", scope, bug["title"], bug["claim"], evidence, "medium", skill, run_id,
                      tags=clean_tags(receipt_tags, bug.get("tags")))
        )
    return entries


def check_receipt(receipt: dict, root: Path) -> list[str]:
    schema = load_schema(root, "receipt.v1.json")
    errors = validate(receipt, schema)
    if errors:
        return errors
    try:
        if parse_time(receipt["ended_at"]) < parse_time(receipt["started_at"]):
            errors.append("$.ended_at: 早于 started_at")
    except ValueError as exc:  # 时间格式在 schema 校验里已拦，这里只兜底
        errors.append(f"$.started_at/ended_at: {exc}")
    if not str(receipt.get("evidence_dir", "")).strip():
        errors.append("$.evidence_dir: 不能为空")
    if not receipt.get("evidence_sha256"):
        errors.append("$.evidence_sha256: 至少需要一个文件哈希")
    return errors


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #

def record_delivery_path(args, receipt_path: Path) -> Path | None:
    """--delivery-out 优先；NO_KB_REQUIRED 未显式给路径时落回执同目录 delivery.json。"""
    if args.delivery_out:
        return Path(args.delivery_out).expanduser()
    if args.no_kb_required:
        return receipt_path.parent / "delivery.json"
    return None


def write_recorded_delivery(path: Path, receipt: dict, entry_ids: list[str]) -> dict:
    scope = receipt.get("scope") if isinstance(receipt.get("scope"), dict) else {}
    data = ensure_delivery(path, receipt["run_id"], scope)
    data["kb_ingest_status"] = "recorded"
    data["kb_entry_ids"] = list(dict.fromkeys([*(data.get("kb_entry_ids") or []), *entry_ids]))
    data["dims"] = {
        "capability": [],
        "project": scope.get("project") or "",
        "device": scope.get("device"),
        "firmware": scope.get("firmware"),
        "profile": "",
        "skill": receipt.get("skill") or "",
    }
    data["updated_at"] = now_bj_text()
    write_delivery(path, data)
    return data


def cmd_record(args) -> int:
    root = resolve_root(args.root)
    receipt_path = Path(args.receipt).expanduser()
    if not receipt_path.is_file():
        raise KBError(f"回执不存在：{receipt_path}")
    receipt = read_json(receipt_path)
    errors = check_receipt(receipt, root)
    if errors:
        raise KBError("回执未通过校验，拒绝入库：\n  " + "\n  ".join(errors))

    run_id = receipt["run_id"]
    delivery_path = record_delivery_path(args, receipt_path)
    checkpoint_arg = (getattr(args, "checkpoint", None) or "").strip()
    if checkpoint_arg:
        known = {
            str(event.get("checkpoint_id"))
            for event in load_wal_events(resolve_outbox_dir(root, None))
        }
        if checkpoint_arg not in known:
            print(f"[error] 未知 checkpoint {checkpoint_arg}：WAL 中不存在，先运行 kb.py checkpoint",
                  file=sys.stderr)
            return 2

    if args.no_kb_required:
        reason = (args.reason or "").strip()
        if not valid_no_kb_reason(reason):
            print(
                "[error] --no-kb-required 必须配 --reason，取值："
                "no-new-knowledge / pure-inventory / duplicate-of-existing:<entry_id> / sensitive-not-indexable",
                file=sys.stderr,
            )
            return 2
        data = ensure_delivery(delivery_path, run_id, receipt.get("scope") or {})
        data["kb_ingest_status"] = "skipped_no_kb"
        data["no_kb_reason"] = reason
        data["updated_at"] = now_bj_text()
        write_delivery(delivery_path, data)
        print(f"回执 {run_id}：无知识价值（{reason}），跳过入库；回执已写 {delivery_path}")
        return 0

    scanner = secret_scan.load_scanner(root, args.skill_git_home, args.allow_missing_scanner)
    if scanner:
        hits = scanner.scan_text(receipt_path.read_text(encoding="utf-8"))
        if hits:
            raise KBError(
                "回执命中凭据规则（skill-git SECRET_PATTERNS 第 "
                + "、".join(str(index) for index in hits)
                + " 条），拒绝写入公开仓库"
            )

    warnings: list[str] = []
    candidates = receipt_to_entries(receipt, receipt_path, root, warnings)
    entries = load_entries(root)
    if any(run_id in (entry.get("validations") or []) and entry["type"] == "run" for entry in entries):
        print(f"回执 {run_id} 已入库，跳过（record 幂等）")
        if delivery_path:
            known = [entry["id"] for entry in entries if run_id in (entry.get("validations") or [])]
            write_recorded_delivery(delivery_path, receipt, known)
        return 0

    registry = load_registry(root, args.registry)
    if registry is None:
        warnings.append("未找到 registry/skills.json，跳过 skill 名登记校验")
    elif receipt.get("skill") not in registry:
        warnings.append(f"skill {receipt.get('skill')} 未在台账登记，条目仍以 pending 入库")

    created, merged, superseded = [], [], []
    merged_entries: list[dict] = []
    for candidate in candidates:
        existing = find_duplicate(entries, candidate)
        if existing is not None:
            merge_entry(existing, candidate)
            merged.append(existing["id"])
            merged_entries.append(existing)
            continue
        candidate_id = candidate["id"]
        suffix = 1
        while any(entry["id"] == candidate_id for entry in entries):
            suffix += 1
            candidate_id = f"{candidate['id'][:-4]}{suffix:04d}"
        candidate["id"] = candidate_id
        entries.append(candidate)
        created.append(candidate)

    if args.supersede:
        old = next((entry for entry in entries if entry["id"] == args.supersede), None)
        if old is None:
            raise KBError(f"--supersede 指向的条目不存在：{args.supersede}")
        replacements = [entry for entry in created if entry["type"] == old["type"]]
        if not replacements:
            raise KBError(f"--supersede 需要同类型的新条目，本次没有生成 {old['type']} 类条目")
        old["status"] = "superseded"
        old["superseded_by"] = replacements[0]["id"]
        old["updated"] = now_iso()
        superseded.append({"id": old["id"], "superseded_by": old["superseded_by"]})

    if checkpoint_arg:
        for entry in [*created, *merged_entries]:
            stamp_checkpoint(entry, checkpoint_arg)

    if not args.dry_run:
        save_entries(root, entries)
        save_indexes(root, entries)
        if delivery_path:
            known = sorted({entry["id"] for entry in entries if run_id in (entry.get("validations") or [])})
            write_recorded_delivery(delivery_path, receipt, known)

    summary = {
        "run_id": run_id,
        "created": [entry["id"] for entry in created],
        "merged": merged,
        "superseded": superseded,
        "warnings": warnings,
        "dry_run": bool(args.dry_run),
        "checkpoint": checkpoint_arg or None,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"回执 {run_id}：新增 {len(created)} 条，合并 {len(merged)} 条，supersede {len(superseded)} 条")
        for entry in created:
            print(f"  + [{entry['type']}] {entry['id']} {entry['title']}")
        for entry_id_value in merged:
            print(f"  ~ 合并到 {entry_id_value}")
        for warning in warnings:
            print(f"  ! {warning}")
    return 0


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #

def query_score(entry: dict, query: dict, registry: dict[str, dict] | None) -> int | None:
    scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
    score = 0
    if query.get("device"):
        device = norm_text(scope.get("device"))
        needle = norm_text(query["device"])
        if device == needle:
            score += 6
        elif device and (needle in device or device in needle):
            score += 4
        elif not device:
            score += 1
        else:
            return None
    if query.get("firmware"):
        firmware = norm_text(scope.get("firmware"))
        needle = norm_text(query["firmware"])
        if firmware == needle:
            score += 2
        elif firmware and (needle in firmware or firmware in needle):
            score += 1
    if query.get("project"):
        project = norm_text(scope.get("project"))
        needle = norm_text(query["project"])
        if project == needle:
            score += 3
        elif project and (needle in project or project in needle):
            score += 2
        elif not project or project == norm_text("通用"):
            score += 1
        # A 项目的例外只对 A 生效，别的项目查询不得被它的 exceptions 污染（v2 §3.2）
        if entry.get("exceptions") and project != needle:
            return None
    if query.get("skill"):
        skill = norm_text(entry.get("source_skill"))
        needle = norm_text(query["skill"])
        if skill == needle:
            score += 4
        elif skill and (needle in skill or skill in needle):
            score += 2
    if query.get("capability"):
        needles = expand_capability(query["capability"])
        best = 0
        for key in capability_keys(entry, registry):
            for needle in needles:
                if key == needle:
                    best = max(best, 5)
                elif needle in key or key in needle:
                    best = max(best, 4)
        if best == 0:
            return None
        score += best
    return score


def summarize_entry(entry: dict, score: int) -> dict:
    evidence = []
    for item in entry.get("evidence", []):
        row = {"kind": item.get("kind"), "ref": item.get("ref")}
        if item.get("sha256"):
            row["sha256"] = item["sha256"]
        if "verified" in item:
            row["verified"] = item["verified"]
        evidence.append(row)
    claim = entry.get("claim", "")
    return {
        "id": entry["id"],
        "type": entry["type"],
        "scope": entry.get("scope"),
        "title": entry.get("title"),
        "claim": claim if len(claim) <= 200 else claim[:197] + "…",
        "confidence": entry.get("confidence"),
        "status": entry.get("status"),
        "source_skill": entry.get("source_skill"),
        "hits": entry.get("hits", 0),
        "score": score,
        "evidence": evidence[:4],
        "evidence_total": len(evidence),
    }


def run_query(entries: list[dict], query: dict, registry: dict[str, dict] | None, top: int,
              entry_type: str | None = None, include_stale: bool = False):
    """query 与 query-back 共用的检索管线：状态过滤、打分、排序、截断。"""
    has_filter = any(query.values())
    allowed_status = {"pending", "active"}
    if include_stale:
        allowed_status.update({"stale", "superseded"})

    scored = []
    for entry in entries:
        if entry.get("status") not in allowed_status:
            continue
        if entry_type and entry.get("type") != entry_type:
            continue
        score = query_score(entry, query, registry) if has_filter else 0
        if has_filter and not score:
            continue
        scored.append((score or 0, entry))

    status_rank = {"active": 2, "pending": 1, "stale": 0, "superseded": -1}
    scored.sort(
        key=lambda pair: (
            pair[0],
            status_rank.get(pair[1].get("status"), 0),
            pair[1].get("hits", 0),
            pair[1].get("created", ""),
        ),
        reverse=True,
    )
    selected = scored[: max(top, 1)]
    return scored, selected, [summarize_entry(entry, score) for score, entry in selected]


def cmd_query(args) -> int:
    root = resolve_root(args.root)
    registry = load_registry(root, args.registry)
    entries = load_entries(root)
    query = {
        "device": args.device,
        "project": args.project,
        "firmware": args.firmware,
        "skill": args.skill,
        "capability": args.capability,
    }

    scored, selected, hits = run_query(entries, query, registry, args.top, args.type, args.include_stale)

    if not args.no_hit_count and selected:
        touched = {entry["id"] for _, entry in selected}
        for entry in entries:
            if entry["id"] in touched:
                entry["hits"] = entry.get("hits", 0) + 1
        try:
            save_entries(root, entries)
        except OSError as exc:
            print(f"[warn] 命中计数写盘失败：{exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(
            {"query": {key: value for key, value in query.items() if value},
             "total": len(scored), "returned": len(hits), "entries": hits},
            ensure_ascii=False, indent=2))
        return 0

    filters = "、".join(f"{key}={value}" for key, value in query.items() if value) or "无条件"
    print(f"查询：{filters}｜命中 {len(hits)} / {len(scored)} 条")
    for item in hits:
        scope = item["scope"] or {}
        where = " · ".join(
            f"{name}={scope.get(name)}" for name in ("device", "project", "firmware") if scope.get(name)
        ) or "通用"
        print(f"\n[{item['status']}] {item['id']}  score={item['score']}  {where}")
        print(f"  {item['title']}")
        print(f"  {item['claim']}")
        for evidence in item["evidence"]:
            digest = f" sha256={evidence['sha256'][:12]}…" if evidence.get("sha256") else ""
            verified = " 已校验" if evidence.get("verified") else ""
            print(f"  - {evidence['kind']}:{evidence['ref']}{digest}{verified}")
        if item["evidence_total"] > len(item["evidence"]):
            print(f"  - 另有 {item['evidence_total'] - len(item['evidence'])} 条证据")
    return 0


def delivery_dimension(delivery: dict, key: str):
    """取 delivery 的查询维度：dims 优先，其次 scope；数组维度取第一个非空值。"""
    dims = delivery.get("dims") if isinstance(delivery.get("dims"), dict) else {}
    scope = delivery.get("scope") if isinstance(delivery.get("scope"), dict) else {}
    value = dims.get(key)
    if value in (None, "", []):
        value = scope.get(key)
    if isinstance(value, list):
        value = next((item for item in value if str(item).strip()), None)
    return value or None


def cmd_query_back(args) -> int:
    root = resolve_root(args.root)
    path = Path(args.delivery).expanduser()
    delivery = load_delivery(path)
    if delivery is None:
        raise KBError(f"delivery 文件不存在：{path}")
    run_id = str(delivery.get("run_id") or "")
    ids = list(dict.fromkeys(
        str(item).strip() for item in (args.entry_id or delivery.get("kb_entry_ids") or []) if str(item).strip()
    ))
    if not ids:
        print(f"[error] run {run_id or '<unknown>'} 没有可回查的 kb_entry_ids", file=sys.stderr)
        return EXIT_INCOMPLETE

    query = {
        "device": args.device or delivery_dimension(delivery, "device"),
        "project": args.project or delivery_dimension(delivery, "project"),
        "firmware": args.firmware or delivery_dimension(delivery, "firmware"),
        "skill": args.skill or delivery_dimension(delivery, "skill"),
        "capability": args.capability or delivery_dimension(delivery, "capability"),
    }
    registry = load_registry(root, args.registry)
    entries = load_entries(root)
    _scored, _selected, hits = run_query(entries, query, registry, args.top)
    found = [item["id"] for item in hits]
    missing = [entry_id_value for entry_id_value in ids if entry_id_value not in found]
    status = "fail" if missing else "pass"
    stamp = now_bj_text()
    update_delivery(path, {
        "kb_query_back_status": status,
        "kb_query_back_at": stamp,
        "kb_query_back_hits": found,
    })

    payload = {
        "run_id": run_id,
        "status": status,
        "queried_at": stamp,
        "dims": {key: value for key, value in query.items() if value},
        "requested": ids,
        "found": found,
        "missing": missing,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif missing:
        print(f"query-back：run {run_id} 状态 fail，{len(missing)}/{len(ids)} 条不可检索：{'、'.join(missing)}")
    else:
        print(f"query-back：run {run_id} 状态 pass，{len(ids)} 条全部可检索（top {args.top}）")
    return EXIT_INCOMPLETE if missing else 0


# --------------------------------------------------------------------------- #
# checkpoint / outbox / promote（事件驱动回流 v2）
# --------------------------------------------------------------------------- #

def cmd_checkpoint(args) -> int:
    root = resolve_root(args.root)
    event_path = Path(args.event).expanduser()
    if not event_path.is_file():
        raise KBError(f"检查点事件不存在：{event_path}")
    event = read_json(event_path)
    if not isinstance(event, dict):
        raise KBError(f"{event_path} 不是 ark.checkpoint.v1 对象")
    errors = validate(event, load_schema(root, "checkpoint.v1.json"))
    if errors:
        print("[error] 检查点未通过校验，拒绝写入 WAL：\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2

    outbox_dir = resolve_outbox_dir(root, args.outbox)
    checkpoint_id_value = checkpoint_id(event)
    event["checkpoint_id"] = checkpoint_id_value
    known = {str(row.get("checkpoint_id")) for row in load_wal_events(outbox_dir)}
    if checkpoint_id_value in known:
        message = f"duplicate checkpoint {checkpoint_id_value}, skipped"
        if args.json:
            print(json.dumps({"checkpoint_id": checkpoint_id_value, "skipped": True,
                              "message": message}, ensure_ascii=False, indent=2))
        else:
            print(message)
        return 0

    day = str(event["at"])[:10].replace("-", "")
    wal_path = outbox_dir / f"checkpoints-{day}.jsonl"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    with wal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    index_path = outbox_index_path(outbox_dir)
    index = load_outbox_index(index_path)
    block = outbox_block(event)
    index[checkpoint_id_value] = block
    save_outbox_index(index_path, index)

    if args.json:
        print(json.dumps({"checkpoint_id": checkpoint_id_value, "skipped": False,
                          "wal": wal_path.name, "outbox": block}, ensure_ascii=False, indent=2))
    else:
        print(f"checkpoint {checkpoint_id_value[:12]}… 已追加到 {wal_path.name}"
              f"（trigger={event['trigger']} stage={event['stage']} quality={event['quality']}）")
    return 0


def cmd_outbox(args) -> int:
    root = resolve_root(args.root)
    outbox_dir = resolve_outbox_dir(root, args.outbox)
    index_path = outbox_index_path(outbox_dir)
    index = load_outbox_index(index_path)
    events = load_wal_events(outbox_dir)

    view = dict(index)
    missing: list[str] = []
    for event in events:
        key = str(event.get("checkpoint_id") or "")
        if key and key not in view:
            view[key] = outbox_block(event)
            missing.append(key)

    replayed = 0
    if args.replay:
        for key in missing:
            index[key] = view[key]
        if missing:
            save_outbox_index(index_path, index)
            replayed = len(missing)

    items = [
        {"checkpoint_id": key, **block}
        for key, block in sorted(view.items(), key=lambda pair: (str(pair[1].get("at") or ""), pair[0]))
        if outbox_matches(block, args.status)
    ]
    pending = [key for key, block in view.items() if outbox_state(block) == "pending"]

    if args.json:
        print(json.dumps({
            "outbox": outbox_dir.name,
            "total": len(view),
            "pending": len(pending),
            "filter": args.status,
            "replayed": replayed,
            "items": items,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"outbox {outbox_dir.name}：{len(view)} 个检查点，{len(pending)} 个未关闭"
              f"（筛选 {args.status}，{len(items)} 条）")
        for item in items:
            print(f"  {item['checkpoint_id'][:12]}…  {item.get('trigger')}  stage={item.get('stage')}"
                  f"  archive={item.get('archive_status')} ingest={item.get('kb_ingest_status')}"
                  f" query_back={item.get('kb_query_back_status')}")
        if args.replay:
            print(f"  已从 WAL 补写 {replayed} 条索引（WAL 未改动）")
    return 0


def entry_project_markers(entry: dict) -> set[str]:
    markers: set[str] = set()
    scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
    project = str(scope.get("project") or "").strip()
    if project and project not in GENERIC_PROJECTS:
        markers.add(project)
    for item in entry.get("applies_to") or []:
        text = str(item).strip()
        if text:
            markers.add(text)
    for tag in entry.get("tags") or []:
        text = str(tag).strip()
        if text.startswith(PROJECT_TAG_PREFIX):
            value = text[len(PROJECT_TAG_PREFIX):].strip()
            if value:
                markers.add(value)
    for item in entry.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        parts = [part for part in str(item.get("ref", "")).split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.lower() in ("project", "projects"):
                markers.add(parts[index + 1])
    return markers


def project_specific_fields(entry: dict) -> list[str]:
    scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
    fields = [name for name in ("device", "firmware") if scope.get(name)]
    if entry.get("exceptions"):
        fields.append("exceptions")
    return fields


def promotion_candidates(entries: list[dict], min_projects: int) -> list[dict]:
    floor = max(min_projects, 1)
    rows: list[dict] = []
    for entry in entries:
        if entry.get("status") == "superseded":
            continue
        if entry.get("scope_level") not in (None, "project"):
            continue
        if project_specific_fields(entry):
            continue
        projects = sorted(entry_project_markers(entry))
        if len(projects) < floor:
            continue
        promote_to = entry.get("promote_to")
        if promote_to not in ("capability", "global"):
            promote_to = "capability"
        rows.append({
            "entry_id": entry.get("id"),
            "promote_to": promote_to,
            "projects": projects,
            "reason": f"跨 {'、'.join(projects)} 共 {len(projects)} 个项目验证，且无项目专属字段",
        })
    return rows


def cmd_promote(args) -> int:
    root = resolve_root(args.root)
    candidates = promotion_candidates(load_entries(root), args.min_projects)
    payload = {"root": root.name, "min_projects": args.min_projects, "candidates": candidates}
    if args.out:
        out_path = resolve_output_path(root, args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not candidates:
        print(f"promote：没有跨 {args.min_projects} 个项目验证的候选")
    else:
        print(f"promote：{len(candidates)} 个提升候选（只读，不自动提升）")
        for row in candidates:
            print(f"  {row['entry_id']} → {row['promote_to']}  项目={'、'.join(row['projects'])}")
        if args.out:
            print(f"  报告已写入 {args.out}")
    return 0


# --------------------------------------------------------------------------- #
# lint
# --------------------------------------------------------------------------- #

def cmd_lint(args) -> int:
    root = resolve_root(args.root)
    errors: list[str] = []
    warnings: list[str] = []

    entry_schema = load_schema(root, "entry.v1.json")
    index_schema = load_schema(root, "index.v1.json")
    registry = load_registry(root, args.registry)
    if registry is None:
        warnings.append("未找到 registry/skills.json（台账未合入或路径未配置），跳过 skill 名校验")

    entries = load_entries(root)
    seen_ids: dict[str, int] = defaultdict(int)
    by_id = {entry.get("id"): entry for entry in entries if isinstance(entry, dict)}

    for entry in entries:
        label = entry.get("id", "<无 id>")
        for problem in validate(entry, entry_schema):
            errors.append(f"entry {label}: {problem}")
        seen_ids[entry.get("id")] += 1
        if entry.get("status") not in STATUSES:
            errors.append(f"entry {label}: 非法 status {entry.get('status')!r}")
        if not entry.get("evidence"):
            errors.append(f"entry {label}: 没有证据，不得入库")
        evidence = entry.get("evidence")
        for item in evidence if isinstance(evidence, list) else []:
            if not isinstance(item, dict):
                errors.append(f"entry {label}: 证据项应为对象")
                continue
            if item.get("kind") not in EVIDENCE_KINDS:
                errors.append(f"entry {label}: 证据类型非法 {item.get('kind')!r}")
            ref = str(item.get("ref", ""))
            if item.get("kind") == "file" and not ref.startswith(("http://", "https://")):
                path = root / ref
                if path.is_file() and item.get("sha256"):
                    actual = sha256_file(path)
                    if actual != item["sha256"]:
                        errors.append(f"entry {label}: 证据文件哈希不符 {ref}")
                elif not path.is_file():
                    warnings.append(f"entry {label}: 证据文件不在本机 {ref}（按路径 + 哈希登记）")
        source_skill = entry.get("source_skill")
        if source_skill and registry and source_skill not in registry:
            message = f"entry {label}: source_skill {source_skill} 未在台账登记"
            (errors if args.strict else warnings).append(message)
        if entry.get("status") == "superseded":
            target = entry.get("superseded_by")
            if not target:
                errors.append(f"entry {label}: superseded 条目必须写 superseded_by")
            elif target not in by_id:
                errors.append(f"entry {label}: superseded_by 指向不存在的条目 {target}")
        elif entry.get("superseded_by"):
            errors.append(f"entry {label}: 非 superseded 条目不应有 superseded_by")
        try:
            age = datetime.now(timezone.utc) - parse_time(entry.get("updated") or entry.get("created", ""))  # noqa: time-lint  # time-lint:allow
            if entry.get("status") in ("pending", "active") and age > timedelta(days=STALE_DAYS) \
                    and entry.get("hits", 0) == 0:
                warnings.append(f"entry {label}: 超过 {STALE_DAYS} 天零命中，应标 stale")
        except ValueError:
            errors.append(f"entry {label}: 创建/更新时间非法")

    for entry_id_value, count in seen_ids.items():
        if entry_id_value and count > 1:
            errors.append(f"重复条目 id：{entry_id_value}（{count} 次）")

    run_ids = defaultdict(int)
    for entry in entries:
        if entry.get("type") == "run":
            for run_id in entry.get("validations") or []:
                run_ids[run_id] += 1
    for run_id, count in run_ids.items():
        if count > 1:
            errors.append(f"同一回执 run_id 重复入库：{run_id}（{count} 条 run 条目）")

    expected = build_indexes(entries)
    index_dir = root / "index"
    for name in INDEX_NAMES:
        path = index_dir / f"{name}.json"
        if not path.is_file():
            errors.append(f"缺少索引 {path.relative_to(root)}（运行 kb.py index）")
            continue
        payload = read_json(path)
        for problem in validate(payload, index_schema):
            errors.append(f"index {name}: {problem}")
        stored = payload.get("keys", {})
        if not isinstance(stored, dict):
            continue
        exp = expected.get(name, {})
        missing = sorted(set(exp) - set(stored))
        extra = sorted(set(stored) - set(exp))
        drift = [key for key in set(exp) & set(stored) if set(exp[key]) != set(stored[key])]
        if missing:
            errors.append(f"index {name}: 缺少键 {missing[:5]}")
        if extra:
            errors.append(f"index {name}: 多余键 {extra[:5]}")
        if drift:
            errors.append(f"index {name}: 键内容漂移 {drift[:5]}")

    scanner = secret_scan.load_scanner(root, args.skill_git_home, args.allow_missing_scanner)
    if scanner:
        candidates = list((root / "entries").rglob("*.jsonl")) + list((root / "index").glob("*.json"))
        hits = scanner.scan_files(candidates)
        for path, patterns in hits.items():
            errors.append(f"凭据规则命中 {path}（第 {'、'.join(map(str, patterns))} 条）")
    else:
        warnings.append("未运行凭据扫描（--allow-missing-scanner）")

    result = {"entries": len(entries), "errors": errors, "warnings": warnings, "strict": bool(args.strict)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"lint：{len(entries)} 条条目，{len(errors)} 个错误，{len(warnings)} 个警告")
        for message in errors:
            print(f"  [error] {message}")
        for message in warnings:
            print(f"  [warn] {message}")
    return EXIT_FAIL if errors else 0


def cmd_index(args) -> int:
    root = resolve_root(args.root)
    registry = load_registry(root, args.registry)
    entries = load_entries(root)
    maps = save_indexes(root, entries)
    summary = "，".join(f"{name}={len(maps[name])} 个键" for name in INDEX_NAMES)
    print(f"索引已重建：{summary}")
    return 0


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #

def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def require_clean(root: Path) -> None:
    status = git(root, "status", "--porcelain")
    if status.returncode != 0:
        raise KBError(f"git status 失败：{status.stderr.strip()}")
    if status.stdout.strip():
        raise KBError("工作区有未提交改动，先提交再 sync：\n" + status.stdout.strip()[:500])


def current_branch(root: Path) -> str:
    result = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        raise KBError(f"读取分支失败：{result.stderr.strip()}")
    return result.stdout.strip()


def cmd_sync(args) -> int:
    root = resolve_root(args.root)
    if git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise KBError(f"{root} 不是 git 仓库")
    branch = args.branch or current_branch(root)
    upstream = args.upstream
    if not upstream:
        tracked = git(root, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
        upstream = tracked.stdout.strip() if tracked.returncode == 0 else "main"
        if upstream.startswith(f"{args.remote}/"):
            upstream = upstream[len(args.remote) + 1:]
    steps = []

    fetched = git(root, "fetch", "--prune", args.remote)
    if fetched.returncode != 0:
        raise KBError(f"git fetch 失败：{fetched.stderr.strip()}")
    steps.append(f"fetch {args.remote}")

    if not args.no_pull:
        pulled = git(root, "pull", "--rebase", args.remote, upstream)
        if pulled.returncode != 0:
            raise KBError(f"git pull --rebase {args.remote}/{upstream} 失败：{pulled.stderr.strip()}")
        steps.append(f"pull --rebase {args.remote}/{upstream}")
        branch = current_branch(root)

    if args.push:
        if branch in ("main", "master"):
            raise KBError(f"拒绝直接推送 {branch}：知识条目一律走功能分支，合并由人工批准")
        require_clean(root)
        pushed = git(root, "push", "-u", args.remote, f"HEAD:{branch}")
        if pushed.returncode != 0:
            raise KBError(f"git push 失败：{pushed.stderr.strip()}")
        steps.append(f"push {args.remote} HEAD:{branch}")

    payload = {"branch": branch, "upstream": upstream, "steps": steps, "pushed": bool(args.push)}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
          f"sync 完成：分支 {branch}，upstream {upstream}，步骤 {', '.join(steps)}")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb.py",
                                     description="ark-kb 知识库工具："
                                                 "record / checkpoint / outbox / promote / query / query-back / lint / sync")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target):
        target.add_argument("--root", help="知识库根目录（默认本仓库）")
        target.add_argument("--registry", help="能力台账路径（默认 registry/skills.json）")
        target.add_argument("--skill-git-home", help="skill-git 仓库路径（凭据扫描器来源）")
        target.add_argument("--allow-missing-scanner", action="store_true",
                            help="允许跳过凭据扫描（仅离线自检，公开写入不要用）")
        target.add_argument("--json", action="store_true", help="输出 JSON")

    record = sub.add_parser("record", help="回执归一成条目并更新索引")
    common(record)
    record.add_argument("--receipt", required=True, help="run.receipt.v1 回执路径")
    record.add_argument("--supersede", help="把旧条目标为 superseded，指向本次生成的新条目")
    record.add_argument("--dry-run", action="store_true", help="只算不写")
    record.add_argument("--delivery-out", help="写入/合并 ark.delivery.v1 回执的路径（receipts/delivery.json）")
    record.add_argument("--no-kb-required", action="store_true",
                        help="本次无知识价值：不写条目，只记 skipped_no_kb")
    record.add_argument("--reason",
                        help="--no-kb-required 的理由（no-new-knowledge / pure-inventory / "
                             "duplicate-of-existing:<entry_id> / sensitive-not-indexable）")
    record.add_argument("--checkpoint", help="把本次条目挂到 WAL 中已存在的 checkpoint_id 上")
    record.set_defaults(func=cmd_record)

    checkpoint = sub.add_parser("checkpoint", help="校验生命周期事件并追加到 append-only WAL")
    checkpoint.add_argument("--root", help="知识库根目录（默认本仓库）")
    checkpoint.add_argument("--outbox", default="receipts/outbox",
                            help="WAL 与 outbox 目录（默认 receipts/outbox，相对知识库根）")
    checkpoint.add_argument("--event", required=True, help="ark.checkpoint.v1 事件 JSON 路径")
    checkpoint.add_argument("--json", action="store_true", help="输出 JSON")
    checkpoint.set_defaults(func=cmd_checkpoint)

    outbox = sub.add_parser("outbox", help="查看检查点 outbox 状态并从 WAL 恢复索引")
    outbox.add_argument("--root", help="知识库根目录（默认本仓库）")
    outbox.add_argument("--outbox", default="receipts/outbox",
                        help="WAL 与 outbox 目录（默认 receipts/outbox，相对知识库根）")
    outbox.add_argument("--status", choices=OUTBOX_STATUSES, default="pending",
                        help="按状态筛选（默认 pending）")
    outbox.add_argument("--replay", action="store_true", help="从 WAL 补写 outbox.json 缺失的行")
    outbox.add_argument("--json", action="store_true", help="输出 JSON")
    outbox.set_defaults(func=cmd_outbox)

    promote = sub.add_parser("promote", help="扫描跨项目提升候选（只读，不自动提升）")
    promote.add_argument("--root", help="知识库根目录（默认本仓库）")
    promote.add_argument("--min-projects", type=int, default=2, help="至少跨几个项目（默认 2）")
    promote.add_argument("--out", help="候选报告写入路径（默认不写文件，相对知识库根）")
    promote.add_argument("--json", action="store_true", help="输出 JSON")
    promote.set_defaults(func=cmd_promote)

    query = sub.add_parser("query", help="检索条目摘要与证据引用")
    common(query)
    query.add_argument("--device")
    query.add_argument("--project")
    query.add_argument("--firmware")
    query.add_argument("--skill")
    query.add_argument("--capability")
    query.add_argument("--type", choices=ENTRY_TYPES)
    query.add_argument("--top", type=int, default=5)
    query.add_argument("--include-stale", action="store_true", help="包含 stale / superseded")
    query.add_argument("--no-hit-count", action="store_true", help="不写命中计数")
    query.set_defaults(func=cmd_query)

    query_back = sub.add_parser("query-back", help="record 后用相同维度回查条目是否可检索")
    common(query_back)
    query_back.add_argument("--delivery", required=True, help="ark.delivery.v1 回执路径")
    query_back.add_argument("--entry-id", action="append",
                            help="覆盖 delivery 里的 kb_entry_ids，可重复")
    query_back.add_argument("--device")
    query_back.add_argument("--project")
    query_back.add_argument("--firmware")
    query_back.add_argument("--skill")
    query_back.add_argument("--capability")
    query_back.add_argument("--top", type=int, default=20)
    query_back.set_defaults(func=cmd_query_back)

    lint = sub.add_parser("lint", help="校验条目、证据、索引与凭据")
    common(lint)
    lint.add_argument("--strict", action="store_true", help="警告也按错误处理")
    lint.set_defaults(func=cmd_lint)

    sync = sub.add_parser("sync", help="与远端同步，推送只允许功能分支")
    common(sync)
    sync.add_argument("--remote", default="origin")
    sync.add_argument("--branch", help="要推送的分支（默认当前分支）")
    sync.add_argument("--upstream", help="拉取的上游分支（默认当前分支的 tracking，否则 main）")
    sync.add_argument("--no-pull", action="store_true", help="只 fetch，不 pull")
    sync.add_argument("--push", action="store_true", help="推送到功能分支")
    sync.set_defaults(func=cmd_sync)

    index = sub.add_parser("index", help="重建索引")
    common(index)
    index.set_defaults(func=cmd_index)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KBError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return EXIT_FAIL
    except secret_scan.ScannerUnavailable as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
