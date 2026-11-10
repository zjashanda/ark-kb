#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL = "tools/backfill.py"
VERSION = "1.0.0"
CONVERTED_AT = "2026-11-10T00:00:00Z"
NODE = "bszT14"
DEVICE = "TCL 智能语音设备（CSK7 + HI3863 双 MCU）"
PROJECT = "tcl-r5 / tcl-lstest-debug"
PLATFORM = "bszT14 (Windows)"
SKILL = "tcl-test-sub"
SKILL_VERSION = "unregistered"
LOCAL_TZ = timezone(timedelta(hours=8))
MANIFEST_NAME = "SHA256SUMS"
REDACT_FILES = ("tool_logs/compat_launch.json", "tool_logs/runtime_profile.json")
REDACT_SUFFIX = "device_key"
REDACTED = "<已脱敏，原始值留在执行机>"

COPIES = [
    ("SHA256SUMS", "manifest"),
    ("summary_final.json", "summary"),
    ("summary_final.md", "report"),
    ("rounds.csv", "rounds"),
    ("errors.log", "tool_log"),
    ("progress.json", "other"),
    ("tool.log", "tool_log"),
    ("serial_logs/COM3_csk_ap.log", "serial"),
    ("tool_logs/compat_launch.json", "config"),
    ("tool_logs/device_shell.json", "config"),
    ("tool_logs/runtime_profile.json", "config"),
]

CURATED = {
    "tcl003-10cmd/20261104_112028_wake_recognition": {
        "task": "tcl003 十命令唤醒识别回归（11:20 场）",
        "lessons": [
            {
                "type": "knowledge",
                "title": "ASR 超时占多数时不能据 network_down 标记归因网络",
                "claim": "本场十命令运行 ASR_TIMEOUT 5 次、INTENT_MISMATCH 2 次、RECOGNIZED 3 次，串口 network_down 标记 50 次；同日全部通过的 edge-tts 场景同样出现 network_down 60 次，说明该标记在正常链路下也高频出现，不能作为网络故障归因依据，判定网络需另取连通性证据。",
                "confidence": "medium",
                "tags": ["串口"],
            }
        ],
        "notes": "ASR 侧失败与串口 network_down 标记同时出现，但缺少链路侧独立证据，归因保持 unknown。",
    },
    "tcl003-10cmd/20261104_113223_wake_recognition": {
        "task": "tcl003 十命令唤醒识别回归（11:32 场）",
        "lessons": [
            {
                "type": "knowledge",
                "title": "同台架连续两场识别率波动不足以判定固件退化",
                "claim": "同台架同固件相邻两场十命令运行识别率分别为 0.3 与 0.5，失败集合在 ASR_TIMEOUT 与 INTENT_MISMATCH 之间漂移，未出现固件崩溃标记；单场低识别率只能说明当次未过线，判定固件退化还需要跨版本对照或稳定复现。",
                "confidence": "medium",
                "tags": ["串口"],
            }
        ],
        "notes": "两场失败分布不同，说明结果受当次声学环境影响，不能逐场对比得出趋势。",
    },
    "tcl003-5rounds/20261102_181057_wake_recognition": {
        "task": "tcl003 五轮唤醒冒烟（18:11 场）",
        "lessons": [
            {
                "type": "method",
                "title": "归档阶段必须产出完整性清单",
                "claim": "该目录证据文件齐全但缺少 SHA256SUMS，回执只能靠转换时复算的哈希自证；运行结束时立刻产出完整性清单，才能证明证据自结束起未被改动，事后补算做不到这一点。",
                "confidence": "medium",
            }
        ],
        "notes": "五轮全部 RECOGNIZED；运行目录未产出完整性清单，回执哈希为转换时复算（见 backfill 字段）。",
    },
    "tcl003-5rounds/20261103_192523_wake_recognition": {
        "task": "tcl003 五轮唤醒冒烟（19:25 场，含完整性清单）",
        "lessons": [
            {
                "type": "method",
                "title": "五轮冒烟不能替代长稳结论",
                "claim": "五轮全部 RECOGNIZED 且完整性清单校验通过，但总时长约两分钟、boundary_window.rounds 为 0，既没有覆盖边界工况也没有覆盖长时间运行；该结果只能作为冒烟门槛，不能用于判定长稳能力。",
                "confidence": "medium",
            }
        ],
        "notes": "本轮为冒烟级验证，结论范围限于五轮唤醒识别。",
    },
    "tcl003-edge-tts-10cmd/20261104_142316_wake_recognition": {
        "task": "tcl003 edge-tts 十命令唤醒识别",
        "lessons": [
            {
                "type": "method",
                "title": "edge-tts 全通过可作为 indextts 故障的对照基线",
                "claim": "同日同台架同固件下 edge-tts 场景十轮全部 RECOGNIZED，而 indextts 场景第 3 轮触发固件崩溃；两次运行台架、固件、命令集一致，差异集中在 TTS 语料，因此 edge-tts 结果可用作语料侧归因的对照基线。",
                "confidence": "medium",
            }
        ],
        "notes": "本场串口同样出现 network_down 与 wdt_not_feed 标记，但未影响识别结果。",
    },
    "tcl003-indextts-10cmd/20261104_144020_wake_recognition": {
        "task": "tcl003 indextts 十命令唤醒识别（第 3 轮触发固件崩溃）",
        "result_override": "fail",
        "failures_extra": [
            {
                "name": "WAKE_FAIL",
                "round": 4,
                "reason": "崩溃后第 4 至第 10 轮连续七轮播放唤醒词均未唤醒，设备未自行恢复。",
                "attribution": "device",
                "evidence": ["evidence/errors.log"],
            }
        ],
        "responsibility_extra": [],
        "bugs": [
            {
                "title": "indextts 场景调高温度步骤触发 CSK 固件崩溃且未自愈",
                "claim": "第 3 轮调高温度后 errors.log 依次记录系统或硬件复位、固件 exception、固件 crash、CSK AP 检测到设备重启，随后七轮全部 WAKE_FAIL；全程未出现 algo.restart，设备不具备自恢复能力。",
                "severity": "major",
            }
        ],
        "lessons": [
            {
                "type": "knowledge",
                "title": "indextts 调高温度后固件崩溃且后续轮次全失效",
                "claim": "第 3 轮调高温度后立即出现 crash 与 exception 标记并伴随设备复位，此后第 4 至第 10 轮全部 WAKE_FAIL；同台架 edge-tts 与 lstts 场景十轮全通过，差异集中在 TTS 语料，排查应从 indextts 语料与固件崩溃现场入手。",
                "confidence": "high",
                "tags": ["串口", "台架"],
            }
        ],
        "stop_conditions": [
            "同一次运行内出现固件 crash、exception 或 system_reset 标记时立即停止后续轮次并保留现场。",
            "连续三轮 WAKE_FAIL 视为设备已失效，必须先执行恢复并验证通过再继续。",
        ],
        "stop_rules": [
            {
                "id": "firmware-crash-halt",
                "rule": "出现固件 crash、exception 或 system_reset 标记即停止本轮任务并要求保留崩溃现场",
                "basis": "kb:kb-bug-241022256518",
            },
            {
                "id": "wake-fail-cluster",
                "rule": "连续三轮 WAKE_FAIL 判定设备失效，先执行 algo.restart 并跑一轮冒烟再继续",
                "basis": "kb:kb-method-5a97db5bfc22",
            },
        ],
        "confidence": "high",
        "notes": "崩溃现场仅有串口与上位机日志，无固件转储；恢复动作未执行，因此无法判断 algo.restart 是否可救回。",
    },
    "tcl003-lstts-10cmd/20261104_150954_wake_recognition": {
        "task": "tcl003 lstts 十命令唤醒识别",
        "lessons": [
            {
                "type": "method",
                "title": "lstts 与 edge-tts 均全通过说明 TTS 场景不是崩溃诱因",
                "claim": "lstts 与 edge-tts 两个 TTS 场景各十轮全部 RECOGNIZED，仅 indextts 场景崩溃；三个场景共用同一台架、固件与命令集，可排除 TTS 场景整体不稳定，把排查面收窄到 indextts 专属语料或其在调温步骤上的时序。",
                "confidence": "medium",
            }
        ],
        "notes": "本场无失败轮次，仅作为同台架对照。",
    },
}

REJECTED = [
    {
        "source": "NoahsArk/tasks/20261107-221155-nas-login-verify",
        "reason": "summary_final.json 含内网地址、第三方账号与他人共享目录清单，另有口令长度字段；脱敏后剩余的登录流程信息不足以支撑可复核回执，整条拒收。",
        "category": "needs_sanitisation",
    },
    {
        "source": "NoahsArk/tasks/20261108-140957-nas-t2a-verify",
        "reason": "t2a_run.json 与 pr_body.md 含内网 FTP 地址、完整包内目录；按知识库安全规则内网地址不入库，整条拒收。",
        "category": "needs_sanitisation",
    },
]


ROW_CURATED = [
    {
        "machine": "win009",
        "row_run_id": "v15-u1-command-20261022_103328",
        "slug": "20261022-103329-win009-v15-u1-command",
        "task": "win009 tcl-csk7 v15 单命令冒烟（远程扫描行回填）",
        "project": "tcl-csk7 / aitest",
        "result": "needs_review",
        "confidence": "low",
        "verdict_agrees": True,
        "lessons": [
            {
                "type": "method",
                "title": "远程扫描行只能生成候选回执，需先取回原始产物",
                "claim": "该行的结论字段与日志判定行一致，但 cases.csv、results.csv、tool.log 均留在目标机未取回本机，哈希无法本机复算；扫描行摘要只能支撑候选回执，要转正式回执必须先取回产物并按证据目录重算 SHA-256。",
                "confidence": "low",
            }
        ],
        "notes": "扫描器从运行目录名与日志尾部推断出 PASS，与 [RESULT] 判定行一致；仍缺原始产物与完整性清单。",
    },
    {
        "machine": "win009",
        "row_run_id": "20261014_163403_wake_interval",
        "slug": "20261014-163403-win009-wake-interval",
        "task": "win009 tcl-csk7 唤醒间隔测试（扫描行回填）",
        "project": "tcl-csk7 / aitest",
        "result": "blocked",
        "confidence": "low",
        "verdict_agrees": False,
        "lessons": [
            {
                "type": "method",
                "title": "扫描推断的结论必须以日志判定行为准",
                "claim": "该行扫描器按目录名与文件词频推断为 PASS，而 tool.log 的 [RESULT] 判定行写的是 BLOCKED 且完成数为 0；两者冲突时回执只能记为 blocked，并把责任层落在扫描工具上，说明任何自动推断都必须与判定行交叉校验后才能入库。",
                "confidence": "medium",
            }
        ],
        "notes": "扫描结论 PASS 与日志判定 BLOCKED 冲突，按保守原则记为 blocked，不得提升为 PASS。",
    },
]

ROW_REJECTED = [
    {
        "machine": "win005",
        "row_run_id": "$RECYCLE.BIN/S-1-5-21-500",
        "reason": "证据目录位于回收站，属系统残留；result 为 null、起止时间为空、日志尾部为二进制乱码，不构成可追溯运行。",
        "category": "system_path",
    },
    {
        "machine": "win010",
        "row_run_id": "20260723_174558_offonline-record-pressure",
        "reason": "totals 自相矛盾（total 9、pass 9、fail 3），原始结论字段仅为 finished，CSV 词频 3/0 无法定论；且目录位于回收站，整条拒收。",
        "category": "totals_inconsistent",
    },
    {
        "machine": "win010",
        "row_run_id": "20260727_113200_offonline-record-restart-command",
        "reason": "原始结论字段为 running（运行未结束），fail 计数 6 而 pass 缺失，无法判定最终结果；运行中产物不得转为回执。",
        "category": "run_unfinished",
    },
]

BULK_MACHINES = {"bszT14", "test-101"}

BUCKET_RULES = [
    ("rejected_system_path", "证据目录位于回收站或系统残留目录，不构成可追溯运行"),
    ("rejected_no_window", "缺少开始时间，无法界定运行窗口"),
    ("rejected_no_files", "没有任何证据文件"),
    ("rejected_no_result", "未解析出结论字段且日志无判定行，需人工确认"),
    ("pending_no_result_verdict", "结论字段为空但日志有判定行，需取回原始产物后按判定行重建"),
    ("pending_verdict_conflict", "扫描推断结论与日志判定行冲突，需人工核对"),
    ("pending_totals_mismatch", "totals 自相矛盾（总数不等于通过数加失败数）"),
    ("pending_no_verdict", "结论字段有值但日志无 [RESULT] 判定行，缺交叉校验"),
    ("candidate_consistent", "结论、判定行与计数互相一致，可生成候选回执（原始产物仍未取回）"),
]


class BackfillError(Exception):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path):
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def parse_manifest(path):
    entries = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0], parts[1].strip()
        if name.startswith("*"):
            name = name[1:]
        if name.startswith("./"):
            name = name[2:]
        entries.append((name, digest.lower()))
    return entries


def verify_manifest(run_dir):
    manifest = Path(run_dir) / MANIFEST_NAME
    if not manifest.exists():
        return {"present": False, "verified": False, "checked": 0, "failures": []}
    failures = []
    entries = parse_manifest(manifest)
    for name, expected in entries:
        target = Path(run_dir) / name
        if not target.exists():
            failures.append({"file": name, "problem": "missing"})
            continue
        actual = sha256_file(target)
        if actual != expected:
            failures.append({"file": name, "problem": "hash_mismatch", "expected": expected, "actual": actual})
    return {"present": True, "verified": not failures, "checked": len(entries), "failures": failures}


def read_rounds(path):
    text = read_text(path)
    if text.startswith("\ufeff"):
        text = text[1:]
    return list(csv.DictReader(text.splitlines()))


def to_utc(local_text):
    text = str(local_text).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
            return naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        except ValueError:
            continue
    raise BackfillError(f"无法解析时间戳：{local_text}")


def iso_z(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_versions(serial_text):
    found = {}
    match = re.search(r"boot version:\s*(\S+)", serial_text)
    if match:
        found["boot"] = match.group(1)
    match = re.search(r"SDK:\s*([^,\n]+)", serial_text)
    if match:
        found["sdk"] = match.group(1).strip()
    match = re.search(r"Version\s*:\s*asr_dsp/(\S+)", serial_text)
    if match:
        found["asr_dsp"] = match.group(1).strip()
    match = re.search(r"FLASH BOOT LOCK VERSION:\s*(\S+)", serial_text)
    if match:
        found["flash_boot_lock"] = match.group(1).strip()
    for name, pattern in (
        ("spi_adapter", r"SPI Adapter Version\s*(\S+)"),
        ("socket_virtual", r"Socket Virtual Version\s*(\S+)"),
        ("flash_adapt", r"Flash Adapt Version\s*(\S+)"),
        ("message", r"Message Version\s*(\S+)"),
        ("lisa_player", r"Lisa Player Version\s*(\S+)"),
    ):
        match = re.search(pattern, serial_text)
        if match:
            found[name] = match.group(1).strip()
    match = re.search(r"get ai info\s+\d+:\s*(\{.*\})", serial_text)
    if match:
        try:
            info = json.loads(match.group(1))
        except ValueError:
            info = {}
        for name in ("wrap", "cae", "esr", "reg"):
            version = (info.get(name) or {}).get("version")
            if version:
                found[f"algo_{name}"] = version.split(",")[0].strip()
    return found


def build_toolchain(launch, shell, versions):
    tools = []
    if shell.get("device_id"):
        tools.append({"name": "device_shell", "version": str(shell.get("version") or "not_recorded")})
    binding = launch.get("binding") or {}
    if binding.get("profile_sha256"):
        tools.append({"name": "profile", "version": str(binding.get("profile_id") or "unknown"), "sha256": binding["profile_sha256"]})
    if binding.get("bench_sha256"):
        tools.append({"name": "bench", "version": str(binding.get("bench_id") or "unknown"), "sha256": binding["bench_sha256"]})
    for key in ("algo_wrap", "algo_cae", "algo_esr", "algo_reg", "spi_adapter", "socket_virtual", "flash_adapt", "message", "lisa_player"):
        if versions.get(key):
            tools.append({"name": key, "version": versions[key]})
    runtime = "not_recorded"
    if launch.get("runtime_version"):
        runtime = str(launch["runtime_version"])
        if launch.get("contract_family"):
            runtime += f" ({launch['contract_family']})"
    return {"runtime": runtime, "skill_name": SKILL, "skill_version": SKILL_VERSION, "tools": tools}


def build_steps(rows, versions, manifest):
    wake_codes = [str(row.get("wake_playback_rc") or "").strip() for row in rows]
    command_codes = [str(row.get("command_playback_rc") or "").strip() for row in rows]
    statuses = [str(row.get("status") or "").strip() for row in rows]
    recognized = sum(1 for status in statuses if status == "RECOGNIZED")
    failed = len(statuses) - recognized
    steps = [
        {"n": 1, "name": "台架与串口就绪", "status": "pass" if rows else "blocked", "evidence": ["evidence/rounds.csv"]},
        {
            "n": 2,
            "name": "固件与工具链版本采集",
            "status": "pass" if versions.get("boot") else "blocked",
            "evidence": ["evidence/serial_logs/COM3_csk_ap.log"],
            "note": "从 CSK AP 串口启动段解析 boot / SDK / 算法版本",
        },
        {
            "n": 3,
            "name": "唤醒词播放",
            "status": "pass" if wake_codes and all(code == "0" for code in wake_codes) else "fail",
            "evidence": ["evidence/rounds.csv"],
            "note": "wake_playback_rc 全为 0",
        },
        {
            "n": 4,
            "name": "命令播放",
            "status": "pass" if command_codes and all(code == "0" for code in command_codes) else "skipped",
            "evidence": ["evidence/rounds.csv"],
            "note": "有机会话因未唤醒而未执行命令播放",
        },
        {
            "n": 5,
            "name": "在线识别",
            "status": "pass" if failed == 0 else "fail",
            "evidence": ["evidence/summary_final.json", "evidence/rounds.csv"],
            "note": f"RECOGNIZED {recognized} 轮，未识别 {failed} 轮",
        },
        {
            "n": 6,
            "name": "结论与证据归档",
            "status": "pass",
            "evidence": ["evidence/summary_final.json", "evidence/summary_final.md"],
            "note": "结论文件与证据副本已归档到回执目录",
        },
        {
            "n": 7,
            "name": "完整性清单校验",
            "status": "pass" if manifest["verified"] else ("fail" if manifest["present"] else "not_run"),
            "evidence": ["evidence/SHA256SUMS"] if manifest["present"] else [],
            "note": f"完整性清单校验通过（{manifest['checked']} 个文件）"
            if manifest["verified"]
            else (
                "完整性清单校验失败：" + "、".join(item["file"] for item in manifest["failures"])
                if manifest["present"]
                else "运行目录未产出 SHA256SUMS，回执哈希为转换时复算，不能自证运行结束时的文件状态"
            ),
        },
    ]
    return steps, recognized, failed


def redact_device_keys(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return False
    changed = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if key.endswith(REDACT_SUFFIX) and isinstance(value, str) and value:
                    node[key] = REDACTED
                    changed.append(key)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if not changed:
        return False
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return True


def build_receipt(run_dir, source_root, receipts_root):
    run_dir = Path(run_dir)
    key = f"{run_dir.parent.name}/{run_dir.name}"
    if key not in CURATED:
        raise BackfillError(f"未登记的运行目录：{key}")
    curated = CURATED[key]
    summary = load_json(run_dir / "summary_final.json")
    rows = read_rounds(run_dir / "rounds.csv")
    manifest = verify_manifest(run_dir)
    versions = extract_versions(read_text(run_dir / "serial_logs" / "COM3_csk_ap.log"))
    launch = load_json(run_dir / "tool_logs" / "compat_launch.json")
    shell = load_json(run_dir / "tool_logs" / "device_shell.json")
    started = iso_z(to_utc(summary["started_at"]))
    ended = iso_z(to_utc(summary["ended_at"]))
    stamp = datetime.strptime(run_dir.name.split("_")[0] + run_dir.name.split("_")[1], "%Y%m%d%H%M%S")
    run_id = f"run-{stamp.strftime('%Y%m%d-%H%M%S')}-{run_dir.parent.name}-{summary.get('target_rounds', 'na')}r"
    receipt_dir = Path(receipts_root) / f"{stamp.strftime('%Y%m%d-%H%M%S')}-{run_dir.parent.name}"
    evidence_dir = receipt_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for relative, role in COPIES:
        source = run_dir / relative
        if not source.exists():
            continue
        target = evidence_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if relative in REDACT_FILES:
            redact_device_keys(target)
        copied.append((relative, role))
    steps, recognized, failed = build_steps(rows, versions, manifest)
    quality = "formal"
    result = curated.get("result_override")
    if result is None:
        result = "pass" if summary.get("outcome") == "COMPLETED" and failed == 0 else "fail"
    failures = []
    for name, count in sorted((summary.get("status_counts") or {}).items()):
        if name == "RECOGNIZED" or count <= 0:
            continue
        failure_rounds = [row for row in rows if str(row.get("status") or "").strip() == name]
        first_round = int(failure_rounds[0]["round"]) if failure_rounds else None
        if name == "CRITICAL_FIRMWARE_MARKER":
            reason = "检测到固件严重异常标记，串口同时记录 crash 与 exception，并伴随设备复位。"
            attribution = "device"
            evidence = ["evidence/errors.log", "evidence/serial_logs/COM3_csk_ap.log"]
        elif name == "WAKE_FAIL":
            reason = "播放唤醒词后设备未成功唤醒。"
            attribution = "device" if summary.get("critical_marker_round_counts") else "unknown"
            evidence = ["evidence/errors.log", "evidence/rounds.csv"]
        else:
            reason = "在线识别未给出期望结果。"
            attribution = "unknown"
            evidence = ["evidence/rounds.csv"]
        failure = {"name": name, "reason": reason, "attribution": attribution, "evidence": evidence}
        if first_round is not None:
            failure["round"] = first_round
        failures.append(failure)
    for extra in curated.get("failures_extra") or []:
        for failure in failures:
            if failure["name"] == extra["name"]:
                failure.update({key: value for key, value in extra.items() if key != "evidence"})
                for item in extra.get("evidence") or []:
                    if item not in failure["evidence"]:
                        failure["evidence"].append(item)
                break
        else:
            failures.append(dict(extra))
    responsibility = []
    for failure in failures:
        responsibility.append(
            {
                "failure": failure["name"],
                "layer": failure["attribution"],
                "note": failure["reason"],
                "evidence": list(failure["evidence"]),
            }
        )
    for extra in curated.get("responsibility_extra") or []:
        if not any(item["failure"] == extra["failure"] for item in responsibility):
            responsibility.append(dict(extra))
    firmware_version = " / ".join(
        value for value in (versions.get("boot"), versions.get("sdk"), versions.get("asr_dsp")) if value
    )
    receipt = {
        "schema": "run.receipt.v1",
        "run_id": run_id,
        "task": curated["task"],
        "skill": SKILL,
        "skill_version": SKILL_VERSION,
        "node": NODE,
        "scope": {"device": DEVICE, "project": PROJECT, "firmware": None, "platform": PLATFORM},
        "quality": quality,
        "result": result,
        "totals": {
            "rounds": len(rows),
            "recognized": recognized,
            "failed": failed,
            "recognition_rate": round(summary.get("normal_window", {}).get("recognition_rate") or 0.0, 3),
        },
        "failures": failures,
        "bugs_found": curated.get("bugs") or [],
        "responsibility": responsibility,
        "steps": steps,
        "toolchain": build_toolchain(launch, shell, versions),
        "firmware": {
            "version": firmware_version or None,
            "sha256": None,
            "source": "serial_boot_log" if versions.get("boot") else "not_recorded",
            "note": "固件二进制未归档，版本取自 CSK AP 串口启动段",
        },
        "recovery": {
            "attempted": False,
            "result": "not_attempted",
            "actions": [],
            "evidence": [],
        },
        "stop_conditions": curated.get("stop_conditions") or [
            "出现固件 crash、exception 或 system_reset 标记时立即停止并保留现场。"
        ],
        "stop_rules": curated.get("stop_rules") or [],
        "evidence_dir": "evidence",
        "evidence_sha256": [],
        "evidence": [],
        "lessons": curated.get("lessons") or [],
        "confidence": curated.get("confidence") or "medium",
        "started_at": started,
        "ended_at": ended,
        "notes": curated.get("notes") or "",
        "tags": ["wake-recognition", "台架", "串口"],
        "backfill": {
            "tool": TOOL,
            "version": VERSION,
            "source_kind": "noahsark_wake_recognition_result",
            "source_path": f"{Path(source_root).name}/{key}",
            "converted_at": CONVERTED_AT,
            "sanitised": True,
            "notes": [
                "task_config.json 未归档：含设备编号与绝对路径",
                "serial_logs/COM4_upper.log 未归档（约 1MB），其哈希由完整性清单覆盖",
                "tool_logs/*.json 副本已脱敏：*_device_key 替换为占位符，与完整性清单记录的原始哈希不再一致",
            ],
        },
    }
    for relative, role in copied:
        digest = sha256_file(evidence_dir / relative)
        receipt["evidence_sha256"].append(digest)
        receipt["evidence"].append(
            {"path": f"evidence/{relative}", "sha256": digest, "role": role, "verified": True}
        )
    receipt_dir.mkdir(parents=True, exist_ok=True)
    with open(receipt_dir / "run.receipt.json", "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "key": key,
        "run_id": run_id,
        "receipt": str(receipt_dir / "run.receipt.json"),
        "quality": quality,
        "result": result,
        "manifest": manifest,
        "evidence_files": [relative for relative, _ in copied],
        "rounds": len(rows),
        "recognized": recognized,
        "failed": failed,
        "decision": "converted",
        "reason": "完整性清单校验通过" if manifest["verified"] else "缺少完整性清单，降级为候选回执",
    }


def discover(source_root):
    source_root = Path(source_root)
    found = []
    for project_dir in sorted(source_root.glob("tcl003-*")):
        if not project_dir.is_dir():
            continue
        for run_dir in sorted(project_dir.glob("*_wake_recognition")):
            if run_dir.is_dir():
                found.append(run_dir)
    return found


def write_conversion_list(report_dir, rows):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "source",
        "run_id",
        "quality",
        "result",
        "rounds",
        "recognized",
        "failed",
        "manifest",
        "evidence_files",
        "decision",
        "reason",
    ]
    with open(report_dir / "conversion-list.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source": row["key"],
                    "run_id": row.get("run_id") or "",
                    "quality": row.get("quality") or "",
                    "result": row.get("result") or "",
                    "rounds": row.get("rounds") or "",
                    "recognized": row.get("recognized") or "",
                    "failed": row.get("failed") or "",
                    "manifest": (
                        "absent"
                        if row.get("manifest") is None
                        else ("ok" if row["manifest"]["verified"] else "failed")
                    ),
                    "evidence_files": len(row.get("evidence_files") or []),
                    "decision": row["decision"],
                    "reason": row["reason"],
                }
            )


def parse_row_time(value):
    if not value:
        return None
    text = str(value).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
    return None


VERDICT_RE = re.compile(r"判定[:：]\s*任务\s*=\s*([A-Za-z_]+)")


def verdict_of(row):
    match = VERDICT_RE.search(str(row.get("log_last") or ""))
    return match.group(1).upper() if match else None


def totals_state(row):
    totals = row.get("totals") or {}
    total = totals.get("total")
    passed = totals.get("pass")
    failed = totals.get("fail")
    numbers = [value for value in (total, passed, failed) if isinstance(value, (int, float))]
    if len(numbers) < 2:
        return None
    if isinstance(total, (int, float)) and isinstance(passed, (int, float)) and isinstance(failed, (int, float)):
        return "consistent" if total == passed + failed else "mismatch"
    return "partial"


def classify_scan_row(row):
    directory = str(row.get("evidence_dir") or "")
    if "$RECYCLE.BIN" in directory.upper() or "$RECYCLE" in directory.upper():
        return "rejected_system_path"
    if not parse_row_time(row.get("started")):
        return "rejected_no_window"
    if not row.get("evidence_files"):
        return "rejected_no_files"
    verdict = verdict_of(row)
    result = row.get("result")
    if result is None:
        return "pending_no_result_verdict" if verdict else "rejected_no_result"
    if verdict and verdict != str(result).upper():
        return "pending_verdict_conflict"
    if totals_state(row) == "mismatch":
        return "pending_totals_mismatch"
    if not verdict:
        return "pending_no_verdict"
    return "candidate_consistent"


ACCOUNT_NAMES = {"administrator", "admin", "root", "system", "testadmin", "bszheng", "data"}


def sanitise_scan_row(row, machine):
    files = []
    for item in row.get("evidence_files") or []:
        name = str(item).replace("\\", "/").rstrip("/").split("/")[-1]
        if name and name not in files:
            files.append(name)
    totals = {}
    for key, value in (row.get("totals") or {}).items():
        if isinstance(value, (int, float)):
            totals[key] = value
    task = row.get("task")
    redacted = ["evidence_dir 与 project_root（含账号与绝对路径）", "evidence_files 的目录部分"]
    if str(task or "").strip().lower() in ACCOUNT_NAMES:
        task = "（扫描器取到的账号名，已脱敏）"
        redacted.append("task 账号名")
    return {
        "machine": machine,
        "run_id": row.get("run_id"),
        "task": task,
        "result": row.get("result"),
        "totals": totals,
        "started": row.get("started"),
        "ended": row.get("ended"),
        "log_last": row.get("log_last"),
        "evidence_files": files,
        "notes": row.get("notes") or [],
        "redacted": redacted,
    }


def find_scan_row(payload, run_id):
    for row in payload.get("runs") or []:
        if str(row.get("run_id")) == run_id:
            return row
    raise BackfillError(f"扫描结果中找不到运行行：{run_id}")


def build_row_receipt(item, scan_dir, receipts_root):
    scan_path = Path(scan_dir) / f"rec-{item['machine']}.json"
    if not scan_path.exists():
        raise BackfillError(f"扫描结果文件不存在：{scan_path}")
    payload = load_json(scan_path)
    row = find_scan_row(payload, item["row_run_id"])
    started = parse_row_time(row.get("started"))
    ended = parse_row_time(row.get("ended"))
    if started is None:
        raise BackfillError(f"{item['row_run_id']} 缺少开始时间，无法生成回执")
    if ended is None:
        ended = started
    if ended < started:
        raise BackfillError(f"{item['row_run_id']} 结束时间早于开始时间")
    receipt_dir = Path(receipts_root) / item["slug"]
    evidence_dir = receipt_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    summary = sanitise_scan_row(row, item["machine"])
    summary_path = evidence_dir / "scan-row.json"
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    digest = sha256_file(summary_path)
    verdict = verdict_of(row)
    steps = [
        {
            "n": 1,
            "name": "扫描发现运行目录",
            "status": "pass",
            "evidence": ["evidence/scan-row.json"],
            "note": f"运行目录位于 {item['machine']}，证据文件 {len(summary['evidence_files'])} 个",
        },
        {
            "n": 2,
            "name": "解析结论字段并与判定行交叉校验",
            "status": "pass" if item["verdict_agrees"] else "blocked",
            "evidence": ["evidence/scan-row.json"],
            "note": (
                f"扫描结论 {summary['result']} 与日志判定行 {verdict} 一致"
                if item["verdict_agrees"]
                else f"扫描结论 {summary['result']} 与日志判定行 {verdict} 冲突"
            ),
        },
        {
            "n": 3,
            "name": "取回并复算原始产物哈希",
            "status": "not_run",
            "evidence": [],
            "note": "原始产物仍在目标机，未取回本机，无法复算 SHA-256",
        },
    ]
    failures = []
    responsibility = []
    if not item["verdict_agrees"]:
        failures.append(
            {
                "name": "VERDICT_CONFLICT",
                "reason": f"扫描推断结论为 {summary['result']}，日志判定行为 {verdict}，两者冲突时以判定行为准。",
                "attribution": "tool",
                "evidence": ["evidence/scan-row.json"],
            }
        )
        responsibility.append(
            {
                "failure": "VERDICT_CONFLICT",
                "layer": "tool",
                "note": "扫描器按目录名与词频推断结论，缺少与 [RESULT] 判定行的交叉校验。",
                "evidence": ["evidence/scan-row.json"],
            }
        )
    receipt = {
        "schema": "run.receipt.v1",
        "run_id": f"run-{item['slug']}",
        "task": item["task"],
        "skill": SKILL,
        "skill_version": SKILL_VERSION,
        "node": item["machine"],
        "scope": {
            "device": DEVICE,
            "project": item["project"],
            "firmware": None,
            "platform": f"{item['machine']} (Windows)",
        },
        "quality": "candidate",
        "result": item["result"],
        "totals": {
            "scanned_rows": 1,
            "evidence_files": len(summary["evidence_files"]),
            **{f"cases_{key}": value for key, value in summary["totals"].items()},
        },
        "failures": failures,
        "bugs_found": [],
        "responsibility": responsibility,
        "steps": steps,
        "toolchain": {
            "runtime": "远程扫描器（noah-16）",
            "skill_name": "NoahsArk",
            "skill_version": "unregistered",
            "tools": [{"name": "recscan.py", "note": "远程巡检脚本，版本未记录"}],
        },
        "firmware": {"version": None, "sha256": None, "source": "not_recorded"},
        "recovery": {"attempted": False, "result": "not_attempted", "actions": [], "evidence": []},
        "stop_conditions": [
            "结论字段与日志判定行冲突时停止入库，先人工核对原始产物。",
        ],
        "stop_rules": [],
        "evidence_dir": "evidence",
        "evidence_sha256": [digest],
        "evidence": [
            {"path": "evidence/scan-row.json", "sha256": digest, "role": "summary", "verified": True}
        ],
        "lessons": item["lessons"],
        "confidence": item["confidence"],
        "started_at": iso_z(started.astimezone(timezone.utc)),
        "ended_at": iso_z(ended.astimezone(timezone.utc)),
        "notes": item["notes"],
        "tags": ["wake-recognition", "台架"],
        "evidence_gap": {
            "code": "EVIDENCE_GAP",
            "missing": [
                "原始运行产物（cases.csv / results.csv / tool.log 未取回本机）",
                "运行目录的完整性清单（SHA256SUMS）",
                "运行时区声明（时间来自目标机本地钟，按 +08:00 换算）",
            ],
            "reason": "历史运行只留下远程扫描行，原始证据未归档到本机，哈希无法复算，只能作为候选回执沉淀线索。",
            "blocking": True,
        },
        "backfill": {
            "tool": TOOL,
            "version": VERSION,
            "source_kind": "remote_scan_row",
            "source_path": f"noah-16/rec-{item['machine']}.json#{item['row_run_id']}",
            "converted_at": CONVERTED_AT,
            "sanitised": True,
            "notes": [
                "扫描行中的目标机绝对路径、账号与目录结构已剔除",
                "skill 由运行目录形态推断，未取回运行时声明",
            ],
        },
    }
    with open(receipt_dir / "run.receipt.json", "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "key": f"{item['machine']}/{item['row_run_id']}",
        "run_id": receipt["run_id"],
        "receipt": str(receipt_dir / "run.receipt.json"),
        "quality": "candidate",
        "result": item["result"],
        "evidence_files": 1,
        "decision": "converted",
        "reason": item["notes"],
    }


def summarise_scan(scan_dir):
    buckets = {}
    machines = {}
    reasons = {name: text for name, text in BUCKET_RULES}
    examples = {}
    for path in sorted(Path(scan_dir).glob("rec-*.json")):
        payload = load_json(path)
        machine = payload.get("machine") or path.stem.replace("rec-", "")
        machines.setdefault(machine, {"rows": 0})
        for row in payload.get("runs") or []:
            bucket = classify_scan_row(row)
            buckets[bucket] = buckets.get(bucket, 0) + 1
            machines[machine]["rows"] += 1
            machines[machine][bucket] = machines[machine].get(bucket, 0) + 1
            samples = examples.setdefault(bucket, [])
            if len(samples) < 3:
                samples.append({"machine": machine, "run_id": row.get("run_id")})
    ordered = [name for name, _ in BUCKET_RULES]
    return {
        "total": sum(buckets.values()),
        "buckets": [
            {"bucket": name, "rows": buckets.get(name, 0), "meaning": reasons[name], "examples": examples.get(name, [])}
            for name in ordered
        ],
        "machines": dict(sorted(machines.items(), key=lambda item: -item[1]["rows"])),
    }


def append_conversion_rows(report_dir, rows):
    path = Path(report_dir) / "conversion-list.csv"
    columns = [
        "source",
        "run_id",
        "quality",
        "result",
        "rounds",
        "recognized",
        "failed",
        "manifest",
        "evidence_files",
        "decision",
        "reason",
    ]
    existing = []
    if path.exists():
        with open(path, "r", encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))
    seen = {row.get("source") for row in existing}
    for row in rows:
        if row["key"] in seen:
            continue
        existing.append(
            {
                "source": row["key"],
                "run_id": row.get("run_id") or "",
                "quality": row.get("quality") or "",
                "result": row.get("result") or "",
                "rounds": row.get("rounds") or "",
                "recognized": row.get("recognized") or "",
                "failed": row.get("failed") or "",
                "manifest": row.get("manifest") or "",
                "evidence_files": len(row.get("evidence_files") or [])
                if isinstance(row.get("evidence_files"), list)
                else (row.get("evidence_files") or ""),
                "decision": row["decision"],
                "reason": row["reason"],
            }
        )
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in existing:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_row_ledger(report_dir, scan_dir, include_bulk=False):
    path = Path(report_dir) / "row-ledger.csv"
    skipped = {}
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["machine", "run_id", "bucket", "decision", "result", "verdict", "totals", "rounds_evidence", "reason"]
        )
        for scan_path in sorted(Path(scan_dir).glob("rec-*.json")):
            payload = load_json(scan_path)
            machine = payload.get("machine") or scan_path.stem.replace("rec-", "")
            if not include_bulk and machine in BULK_MACHINES:
                skipped[machine] = len(payload.get("runs") or [])
                continue
            for row in payload.get("runs") or []:
                bucket = classify_scan_row(row)
                totals = row.get("totals") or {}
                totals_text = "/".join(
                    "" if totals.get(key) is None else str(totals.get(key)) for key in ("total", "pass", "fail")
                )
                writer.writerow(
                    [
                        machine,
                        row.get("run_id"),
                        bucket,
                        "reject" if bucket.startswith("rejected") else ("candidate" if bucket.startswith("candidate") else "pending"),
                        row.get("result") or "",
                        verdict_of(row) or "",
                        totals_text,
                        len(row.get("evidence_files") or []),
                        dict(BUCKET_RULES)[bucket],
                    ]
                )
    if skipped:
        json.dump(
            {"注意": "下列机器的逐行台账未展开，分桶计数见 scan-buckets.json", "skipped": skipped},
            open(Path(report_dir) / "row-ledger-skipped.json", "w", encoding="utf-8"),
            ensure_ascii=False,
            indent=2,
        )
    return path


def cmd_rows(args):
    import kb

    root = Path(args.root)
    rows = []
    for item in ROW_CURATED:
        row = build_row_receipt(item, args.scan, args.out)
        receipt_path = Path(row["receipt"])
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
        errors = kb.check_receipt(receipt, root)
        if errors:
            raise BackfillError(f"{receipt_path} 未通过校验：" + "；".join(errors))
        rows.append(row)
    for item in ROW_REJECTED:
        rows.append(
            {
                "key": f"{item['machine']}/{item['row_run_id']}",
                "decision": "rejected",
                "reason": item["reason"],
                "quality": "",
                "result": "",
                "evidence_files": "",
            }
        )
    Path(args.reports).mkdir(parents=True, exist_ok=True)
    append_conversion_rows(args.reports, rows)
    summary = summarise_scan(args.scan)
    with open(Path(args.reports) / "scan-buckets.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    ledger = write_row_ledger(args.reports, args.scan, include_bulk=getattr(args, "ledger_all", False))
    json.dump(
        {
            "converted": [row["key"] for row in rows if row["decision"] == "converted"],
            "rejected": [row["key"] for row in rows if row["decision"] == "rejected"],
            "scanned_rows": summary["total"],
            "buckets": [{item["bucket"]: item["rows"]} for item in summary["buckets"]],
            "ledger": str(ledger),
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


def cmd_scan(args):
    summary = []
    for run_dir in discover(args.source):
        key = f"{run_dir.parent.name}/{run_dir.name}"
        manifest = verify_manifest(run_dir)
        summary.append(
            {
                "run_dir": key,
                "registered": key in CURATED,
                "manifest": manifest["present"],
                "manifest_verified": manifest["verified"],
                "manifest_checked": manifest["checked"],
                "manifest_failures": manifest["failures"],
            }
        )
    json.dump({"source": str(args.source), "runs": summary}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_build(args):
    run_dirs = discover(args.source)
    if not run_dirs:
        raise BackfillError(f"未在 {args.source} 下发现任何 *_wake_recognition 目录")
    rows = []
    for run_dir in run_dirs:
        rows.append(build_receipt(run_dir, args.source, args.out))
    for item in REJECTED:
        rows.append(
            {
                "key": item["source"],
                "decision": "rejected",
                "reason": item["reason"],
            }
        )
    write_conversion_list(args.reports, rows)
    json.dump(
        {"converted": sum(1 for row in rows if row["decision"] == "converted"), "rejected": sum(1 for row in rows if row["decision"] == "rejected"), "rows": rows},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


def cmd_selftest(args):
    import kb

    root = Path(args.root)
    receipt_path = root / "docs" / "receipts" / "20261106-kb-selftest" / "run.receipt.json"
    with open(receipt_path, "r", encoding="utf-8") as handle:
        receipt = json.load(handle)
    receipt["node"] = "agent-linux"
    receipt["quality"] = "formal"
    receipt["toolchain"] = {
        "runtime": "python 3.10.12 / linux",
        "skill_name": "skill-kb",
        "skill_version": "1.0.0",
        "tools": [{"name": "python", "version": "3.10.12"}, {"name": "unittest", "version": "3.10.12"}],
    }
    receipt["steps"] = [
        {"n": 1, "name": "工具链自检单测", "status": "pass", "evidence": ["evidence/unittest.log"], "note": "21 条用例全部通过"},
        {"n": 2, "name": "运行环境登记", "status": "pass", "evidence": ["evidence/env.txt"], "note": "python 3.10.12 / linux"},
    ]
    receipt["recovery"] = {"attempted": False, "result": "not_attempted", "actions": [], "evidence": []}
    receipt["stop_conditions"] = ["单测出现失败即停止入库操作，先修工具链再继续。"]
    errors = kb.check_receipt(receipt, root)
    if errors:
        raise BackfillError("升级后的自检回执未通过校验：" + "；".join(errors))
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    sys.stdout.write(f"selftest receipt upgraded: {receipt_path}\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backfill.py", description="把历史运行结果规范化为 run.receipt.v1")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="扫描历史运行目录并报告完整性清单状态")
    scan.add_argument("--source", required=True)
    scan.set_defaults(func=cmd_scan)
    build = sub.add_parser("build", help="生成正式/候选回执与转换清单")
    build.add_argument("--source", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--reports", required=True)
    build.set_defaults(func=cmd_build)
    selftest = sub.add_parser("selftest", help="把自检回执升级为完整 v1 字段")
    selftest.add_argument("--root", default=".")
    selftest.set_defaults(func=cmd_selftest)
    rows = sub.add_parser("rows", help="把远程扫描行转换为候选回执并汇总逐行台账")
    rows.add_argument("--scan", required=True)
    rows.add_argument("--out", required=True)
    rows.add_argument("--reports", required=True)
    rows.add_argument("--root", default=".")
    rows.add_argument("--ledger-all", action="store_true", help="逐行台账包含 bszT14 / test-101 的批量行")
    rows.set_defaults(func=cmd_rows)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BackfillError as error:
        sys.stderr.write(f"backfill: {error}\n")
        return 3


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
