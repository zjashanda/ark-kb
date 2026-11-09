#!/usr/bin/env python3
"""ark-mesh：局域网节点间文件互通（取件 / 归档 / 状态）。

    ark_fetch.py status  [--json]                       节点可达性 + 制品台账 + 缓存
    ark_fetch.py index   --name X --project P --version V --sha256 H --node N --path PATH
    ark_fetch.py fetch   --name X --dest D [--dest-node N] [--timeout S] [--force]
    ark_fetch.py fetch   --source NODE --path P --dest D [--dest-node N]
    ark_fetch.py archive --name X [--version V] [--from-node N]

设计口径见同目录 README.md：
  优先级 本地缓存 → 台账内各来源（按 priority）→ 全部失败才报 BLOCKED；
  每次成功写 artifact-manifest.json；失败写 fetch-failure-report.json 并逐条列出
  尝试过的来源与错误，不允许只回一句“本地没有”。

只用标准库；传输走本机 ssh/scp（本机必须能登录目标节点，今天由 bszT14 充当 relay）。
绝不打印、写入任何凭据。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "ark-mesh-sources.v1"
MANIFEST_NAME = "artifact-manifest.json"
FAILURE_NAME = "fetch-failure-report.json"
EXIT_OK, EXIT_NO_SOURCE, EXIT_USAGE, EXIT_FORBIDDEN = 0, 3, 2, 4

# 凭据类文件名/路径一律拒绝搬运（宁可报错，不碰密钥）
FORBIDDEN = re.compile(
    r"(^|[./\\_\-\s])("
    r"\.env(\..*)?|env|password|passwd|pass|token|secret|credential[s]?|"
    r"key|keys|pem|p12|pfx|ppk|id_rsa|id_ed25519|npmrc|netrc|cookie|cookies|"
    r"auth\.json|git-credentials"
    r")([./\\_\-\s]|$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- 基础


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def die(msg: str, code: int = EXIT_USAGE) -> "NoReturn":  # type: ignore[name-defined]
    print(f"ark-fetch: {msg}", file=sys.stderr)
    raise SystemExit(code)


def default_config_path() -> Path:
    env = os.environ.get("ARK_MESH_CONFIG")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent / "sources.json"
    if here.exists():
        return here
    return Path.home() / ".config" / "ark" / "mesh-sources.json"


def load_config(path: Path | None) -> dict:
    cfg_path = Path(path).expanduser() if path else default_config_path()
    if not cfg_path.exists():
        die(f"来源索引不存在: {cfg_path}（先跑 bootstrap 或 --config 指向它）")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    if cfg.get("schema") != SCHEMA:
        die(f"来源索引 schema 不是 {SCHEMA}: {cfg_path}")
    cfg["_path"] = str(cfg_path)
    cfg.setdefault("nodes", {})
    cfg.setdefault("artifacts", {})
    # sshpass 只认 SSHPASS；由节点的 pass_env 映射过来，口令仍只存在于环境变量里
    for node in cfg["nodes"].values():
        if node.get("auth") == "sshpass-env":
            src = os.environ.get(node.get("pass_env", "ARK_STORAGE_SSH_PASS"))
            if src and not os.environ.get("SSHPASS"):
                os.environ["SSHPASS"] = src
    return cfg


def save_config(cfg: dict) -> None:
    path = Path(cfg.pop("_path"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    cfg["_path"] = str(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n / 1:.1f}{unit}".replace(".0", "")
        n /= 1024.0
    return f"{n}B"


# --------------------------------------------------------------------------- 传输


def node_spec(cfg: dict, name: str) -> dict:
    node = cfg["nodes"].get(name)
    if not node:
        die(f"来源索引里没有节点 {name}；已有: {', '.join(sorted(cfg['nodes']))}")
    return node


class MissingPass(Exception):
    """节点需要口令环境变量但当前进程没有设置。"""


def ssh_base(node: dict) -> list[str]:
    batch = "no" if node.get("auth") == "sshpass-env" else "yes"
    base = ["ssh", "-o", f"BatchMode={batch}", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no", "-p", str(node.get("port", 22))]
    return base


def remote_shell(cfg: dict, name: str) -> list[str]:
    """返回执行远端命令的前缀（ssh / sshpass+ssh）。"""
    node = node_spec(cfg, name)
    cmd = ssh_base(node)
    if node.get("auth") == "sshpass-env":
        env_name = node.get("pass_env", "ARK_STORAGE_SSH_PASS")
        if not os.environ.get(env_name):
            raise MissingPass(f"节点 {name} 需要环境变量 {env_name}（本进程未设置）")
        cmd = ["sshpass", "-e"] + cmd
    return cmd + [f"{node['user']}@{node['host']}"]


def remote_copy_prefix(cfg: dict, name: str) -> list[str]:
    node = node_spec(cfg, name)
    batch = "no" if node.get("auth") == "sshpass-env" else "yes"
    cmd = ["scp", "-o", f"BatchMode={batch}", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=no", "-P", str(node.get("port", 22))]
    if node.get("auth") == "sshpass-env":
        env_name = node.get("pass_env", "ARK_STORAGE_SSH_PASS")
        if not os.environ.get(env_name):
            raise MissingPass(f"节点 {name} 需要环境变量 {env_name}（本进程未设置）")
        cmd = ["sshpass", "-e"] + cmd
    return cmd


def is_windows(node: dict) -> bool:
    return node.get("kind", "linux").lower() == "windows"


def _dec(raw: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def run(cmd: list[str], timeout: float, env: dict | None = None) -> tuple[int, str, str]:
    """执行子进程并取回 stdout/stderr。

    Windows 上不用管道收集输出：Win32-OpenSSH 在 stdout/stderr 是管道时会卡住不退出
    （PowerShell 里手跑同一条命令却正常）。改成写临时文件，顺带用 CREATE_NO_WINDOW
    保证不弹控制台窗口。
    """
    child_env = env or os.environ.copy()
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
            try:
                proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe,
                                      timeout=timeout, env=child_env, creationflags=flags)
            except subprocess.TimeoutExpired:
                return 124, "", f"timeout after {timeout:.0f}s"
            except FileNotFoundError as exc:
                return 127, "", f"missing binary: {exc}"
            fo.seek(0)
            fe.seek(0)
            return proc.returncode, _dec(fo.read()), _dec(fe.read())
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=child_env)
        # Windows 目标机 stderr 常是 GBK/CP936，统一按 utf-8 宽松解码，绝不因编码崩掉
        return (proc.returncode, _dec(proc.stdout), _dec(proc.stderr))
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout:.0f}s"
    except FileNotFoundError as exc:
        return 127, "", f"missing binary: {exc}"


def ps_encoded(script: str) -> str:
    blob = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {blob}"


def win_path(p: str) -> str:
    return p.replace("\\", "/")


def remote_hash(cfg: dict, name: str, path: str, timeout: float) -> tuple[str | None, str]:
    """返回 (sha256 | None, 错误描述)。"""
    node = node_spec(cfg, name)
    if is_windows(node):
        cmd = remote_shell(cfg, name) + [
            ps_encoded(f"if (Test-Path -LiteralPath '{path}') {{ (Get-FileHash -LiteralPath '{path}' -Algorithm SHA256).Hash }} else {{ Write-Output 'ARKMESH_MISSING' }}")
        ]
        rc, out, err = run(cmd, timeout)
        text = out.strip()
        err = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        if rc != 0:
            return None, f"hash 失败(rc={rc}): {(err or text)[:200]}"
        if "ARKMESH_MISSING" in text:
            return None, "源文件不存在"
        match = re.search(r"\b([0-9A-Fa-f]{64})\b", text)
        if not match:
            return None, f"无法解析 hash 输出: {text[:120]}"
        return match.group(1).lower(), ""
    cmd = remote_shell(cfg, name) + [
        f"if [ -f {shq(path)} ]; then sha256sum {shq(path)} | cut -d' ' -f1; "
        f"elif [ -d {shq(path)} ]; then echo ARKMESH_ISDIR; else echo ARKMESH_MISSING; fi"
    ]
    rc, out, err = run(cmd, timeout)
    text = out.strip()
    if rc != 0:
        return None, f"hash 失败(rc={rc}): {(err or text)[:200]}"
    if "ARKMESH_MISSING" in text:
        return None, "源文件不存在"
    if "ARKMESH_ISDIR" in text:
        return None, "路径是目录"
    match = re.search(r"\b([0-9A-Fa-f]{64})\b", text)
    if not match:
        return None, f"无法解析 hash 输出: {text[:120]}"
    return match.group(1).lower(), ""


def shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def ensure_dir(cfg: dict, name: str, path: str, timeout: float) -> tuple[bool, str]:
    node = node_spec(cfg, name)
    if is_windows(node):
        cmd = remote_shell(cfg, name) + [
            ps_encoded(f"New-Item -ItemType Directory -Force -Path '{path}' | Out-Null; Write-Output 'ARKMESH_OK'")
        ]
    else:
        cmd = remote_shell(cfg, name) + [f"mkdir -p {shq(path)} && echo ARKMESH_OK"]
    rc, out, err = run(cmd, timeout)
    if rc != 0 or "ARKMESH_OK" not in out:
        clean = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        return False, f"建目录失败(rc={rc}): {(clean or out)[:200]}"
    return True, ""


def probe_node(cfg: dict, name: str, timeout: float) -> tuple[bool, str, float]:
    node = node_spec(cfg, name)
    started = time.time()
    try:
        return _probe_node(cfg, name, node, timeout, started)
    except MissingPass as exc:
        return False, f"SKIP: {exc}", time.time() - started


def _probe_node(cfg: dict, name: str, node: dict, timeout: float, started: float) -> tuple[bool, str, float]:
    remote = "hostname" if not is_windows(node) else "hostname"
    rc, out, err = run(remote_shell(cfg, name) + [remote], timeout)
    elapsed = time.time() - started
    if rc != 0:
        clean = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        return False, (clean or f"rc={rc}").splitlines()[-1][:160] if (clean or rc) else "", elapsed
    return True, out.strip().splitlines()[0] if out.strip() else "", elapsed


def scp_fetch(cfg: dict, name: str, remote_path: str, local_dest: Path, timeout: float) -> tuple[bool, str]:
    node = node_spec(cfg, name)
    local_dest.parent.mkdir(parents=True, exist_ok=True)
    remote = remote_path.replace("\\", "/") if is_windows(node) else remote_path
    cmd = remote_copy_prefix(cfg, name) + [
        f"{node['user']}@{node['host']}:{remote}", str(local_dest)
    ]
    rc, out, err = run(cmd, timeout)
    if rc != 0:
        clean = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        return False, (clean or out).strip()[:300] or f"rc={rc}"
    return True, ""


def scp_push(cfg: dict, name: str, local_src: Path, remote_path: str, timeout: float) -> tuple[bool, str]:
    node = node_spec(cfg, name)
    remote = remote_path.replace("\\", "/") if is_windows(node) else remote_path
    cmd = remote_copy_prefix(cfg, name) + [
        str(local_src), f"{node['user']}@{node['host']}:{remote}"
    ]
    rc, out, err = run(cmd, timeout)
    if rc != 0:
        clean = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        return False, (clean or out).strip()[:300] or f"rc={rc}"
    return True, ""


# --------------------------------------------------------------------------- 台账


def guard(job: dict) -> None:
    for field in ("name", "path"):
        value = str(job.get(field, ""))
        if FORBIDDEN.search(Path(value).name) or FORBIDDEN.search(value):
            die(
                f"拒绝搬运凭据类文件（命中 {field}={value}）。凭据不允许经 ark-mesh 自动复制，"
                "请在目标节点用官方方式单独配置。",
                EXIT_FORBIDDEN,
            )


def candidates(cfg: dict, artifact: dict, skip_nodes: set[str]) -> list[dict]:
    """按 priority 排序的来源清单；等于 0 优先级表示本地缓存，由 fetch 单独处理。"""
    locs = [dict(loc, _index=i) for i, loc in enumerate(artifact.get("locations", []))]
    locs = [loc for loc in locs if loc.get("node") not in skip_nodes]
    return sorted(locs, key=lambda loc: (loc.get("priority", 100), loc["_index"]))


def cache_path(cfg: dict, artifact: dict) -> Path:
    base = Path(os.environ.get("ARK_MESH_CACHE", cfg.get("cache", {}).get("dir", "~/.cache/ark-mesh"))).expanduser()
    digest = artifact.get("sha256") or "nohash"
    return base / digest[:16] / (artifact.get("filename") or artifact["name"].split("/")[-1])


def write_manifest(dest_dir: Path, record: dict, local: bool) -> Path:
    """在目的目录追加一条制品记录（保留历史，幂等按 sha256+destination 去重）。"""
    if not local:
        return dest_dir / MANIFEST_NAME  # 远端清单由调用方单独写
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / MANIFEST_NAME
    data = {"schema": "ark-artifact-manifest.v1", "artifacts": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"schema": "ark-artifact-manifest.v1", "artifacts": []}
    arts = [a for a in data.get("artifacts", [])
            if not (a.get("sha256") == record["sha256"] and a.get("destination") == record["destination"])]
    arts.append(record)
    data["artifacts"] = arts
    data["updated_at"] = now_iso()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def manifest_path_on(cfg: dict, dest_node: str | None, dest_dir: str) -> str:
    if not dest_node:
        return str(Path(dest_dir) / MANIFEST_NAME)
    node = node_spec(cfg, dest_node)
    sep = "\\" if is_windows(node) else "/"
    return dest_dir.rstrip("\\/") + sep + MANIFEST_NAME


def write_remote_manifest(cfg: dict, dest_node: str, dest_dir: str, record: dict, timeout: float) -> tuple[bool, str]:
    """把一条记录追加进目的节点上的 artifact-manifest.json（用目标节点自己的 python3）。"""
    node = node_spec(cfg, dest_node)
    payload = base64.b64encode(json.dumps(record, ensure_ascii=False).encode("utf-8")).decode("ascii")
    if is_windows(node):
        script = (
            "$ErrorActionPreference='Stop';"
            f"$dir='{dest_dir}';"
            f"$raw=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}'));"
            "$rec=$raw | ConvertFrom-Json;"
            "$p=Join-Path $dir 'artifact-manifest.json';"
            "if (Test-Path -LiteralPath $p) { $d=Get-Content -LiteralPath $p -Raw | ConvertFrom-Json } else { $d=[pscustomobject]@{schema='ark-artifact-manifest.v1';artifacts=@()} };"
            "$list=@($d.artifacts);"
            "$list=@($list | Where-Object { -not ($_.sha256 -eq $rec.sha256 -and $_.destination -eq $rec.destination) });"
            "$list+=$rec;"
            "$out=[pscustomobject]@{schema='ark-artifact-manifest.v1';artifacts=$list;updated_at=(Get-Date).ToString('o')};"
            "$out | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $p -Encoding UTF8;"
            "Write-Output 'ARKMESH_OK'"
        )
        cmd = remote_shell(cfg, dest_node) + [ps_encoded(script)]
    else:
        script = (
            "import base64,json,pathlib,datetime;"
            f"d=pathlib.Path({dest_dir!r});d.mkdir(parents=True,exist_ok=True);"
            f"p=d/'artifact-manifest.json';"
            f"rec=json.loads(base64.b64decode({payload!r}));"
            "data=json.loads(p.read_text()) if p.exists() and p.stat().st_size else {'schema':'ark-artifact-manifest.v1','artifacts':[]};"
            "arts=[a for a in data.get('artifacts',[]) if not (a.get('sha256')==rec['sha256'] and a.get('destination')==rec['destination'])];"
            "arts.append(rec);data['artifacts']=arts;data['updated_at']=datetime.datetime.now().astimezone().isoformat(timespec='seconds');"
            "p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+chr(10));"
            "print('ARKMESH_OK')"
        )
        cmd = remote_shell(cfg, dest_node) + [f"python3 -c {shq(script)}"]
    rc, out, err = run(cmd, timeout)
    if rc != 0 or "ARKMESH_OK" not in out:
        clean = re.sub(r"CLIXML|<Objs.*", "", err, flags=re.S).strip()
        return False, (clean or out)[:200]
    return True, ""


# --------------------------------------------------------------------------- 命令


def cmd_status(cfg: dict, args) -> int:
    timeout = args.timeout
    rows = []
    for name in sorted(cfg["nodes"]):
        ok, info, elapsed = probe_node(cfg, name, timeout)
        rows.append({"node": name, "reachable": ok, "detail": info, "elapsed_s": round(elapsed, 2)})

    arts = []
    for name, art in sorted(cfg["artifacts"].items()):
        cp = cache_path(cfg, art)
        cached = cp.exists() and (not art.get("sha256") or sha256_file(cp) == art["sha256"])
        best = candidates(cfg, art, set())[:1]
        arts.append({
            "name": name, "project": art.get("project"), "version": art.get("version"),
            "bytes": art.get("bytes"), "sha256": art.get("sha256"),
            "cached": cached,
            "sources": [f"{loc['node']}:{loc['path']}" for loc in candidates(cfg, art, set())],
            "best_source": f"{best[0]['node']}:{best[0]['path']}" if best else None,
        })

    if args.json:
        print(json.dumps({"config": cfg["_path"], "nodes": rows, "artifacts": arts,
                          "checked_at": now_iso()}, ensure_ascii=False, indent=2))
        return EXIT_OK

    print(f"来源索引: {cfg['_path']}")
    print(f"{'NODE':<12}{'STATUS':<10}{'SEC':>6}  DETAIL")
    for row in rows:
        status = "PASS" if row["reachable"] else "FAIL"
        print(f"{row['node']:<12}{status:<10}{row['elapsed_s']:>6}  {row['detail'][:70]}")
    print()
    print(f"{'ARTIFACT':<28}{'PROJECT':<12}{'VERSION':<12}{'SIZE':>10}  CACHE  BEST SOURCE")
    for art in arts:
        print(f"{art['name']:<28}{str(art['project'] or '-'):<12}{str(art['version'] or '-'):<12}"
              f"{human(art['bytes'] or 0):>10}  {'yes' if art['cached'] else 'no':<6} {art['best_source'] or '-'}")
    return EXIT_OK if all(r["reachable"] for r in rows) else EXIT_NO_SOURCE


def cmd_index(cfg: dict, args) -> int:
    art = cfg["artifacts"].setdefault(args.name, {
        "name": args.name, "locations": [],
    })
    for key in ("project", "version", "sha256", "bytes", "filename", "note"):
        value = getattr(args, key, None)
        if value is not None:
            art[key] = value
    if args.node and args.path:
        node = node_spec(cfg, args.node)
        node_dir = node.get("base_dir", "")
        path = args.path
        if node_dir and not path.startswith(("/", "D:", "C:", "E:")):
            sep = "\\" if is_windows(node) else "/"
            path = node_dir.rstrip("\\/") + sep + path.lstrip("\\/")
        art["locations"] = [loc for loc in art["locations"]
                            if not (loc["node"] == args.node and loc["path"] == path)]
        art["locations"].append({"node": args.node, "path": path,
                                 "priority": args.priority if args.priority is not None else len(art["locations"]) + 1})
    if args.remove_node:
        art["locations"] = [loc for loc in art["locations"] if loc["node"] != args.remove_node]
    if not art.get("locations") and not args.keep_empty:
        cfg["artifacts"].pop(args.name, None)
        save_config(cfg)
        print(f"已移除制品 {args.name}（无剩余来源）")
        return EXIT_OK
    save_config(cfg)
    print(json.dumps(cfg["artifacts"][args.name], ensure_ascii=False, indent=2))
    return EXIT_OK


def _single_attempt(cfg: dict, art: dict, loc: dict, timeout: float, staging: Path) -> tuple[bool, str, dict]:
    node, path = loc["node"], loc["path"]
    started = time.time()
    attempt = {"source_node": node, "source_path": path, "priority": loc.get("priority")}
    ok, info, probe_elapsed = probe_node(cfg, node, min(timeout, 10))
    if not ok:
        reason = "无口令环境变量" if info.startswith("SKIP:") else "不可达"
        attempt.update(result="unreachable", error=info, elapsed_s=round(time.time() - started, 2))
        return False, f"节点{reason}: {info}", attempt
    try:
        digest, err = remote_hash(cfg, node, path, timeout)
    except MissingPass as exc:
        attempt.update(result="unreachable", error=str(exc), elapsed_s=round(time.time() - started, 2))
        return False, str(exc), attempt
    if digest is None:
        attempt.update(result="source_unusable", error=err, elapsed_s=round(time.time() - started, 2))
        return False, err, attempt
    if art.get("sha256") and digest != art["sha256"]:
        attempt.update(result="hash_mismatch", error=f"源端 sha256={digest} 与台账 {art['sha256']} 不符",
                       elapsed_s=round(time.time() - started, 2))
        return False, attempt["error"], attempt
    stage = staging / (art.get("filename") or Path(path).name)
    ok, err = scp_fetch(cfg, node, path, stage, timeout)
    if not ok:
        attempt.update(result="copy_failed", error=err, elapsed_s=round(time.time() - started, 2))
        return False, err, attempt
    local_digest = sha256_file(stage)
    if digest != local_digest:
        attempt.update(result="transfer_corrupt", error=f"回传后 sha256={local_digest} != 源端 {digest}",
                       elapsed_s=round(time.time() - started, 2))
        return False, attempt["error"], attempt
    attempt.update(result="ok", sha256=local_digest, bytes=stage.stat().st_size,
                   elapsed_s=round(time.time() - started, 2))
    return True, str(stage), attempt


def cmd_fetch(cfg: dict, args) -> int:
    dest_node = args.dest_node
    dest_dir = args.dest
    timeout = args.timeout
    staging = Path(tempfile.mkdtemp(prefix="ark-mesh-"))
    attempts: list[dict] = []
    try:
        if args.source and args.path:
            guard({"name": args.name or Path(args.path).name, "path": args.path})
            art = {"name": args.name or Path(args.path).name, "sha256": args.sha256,
                   "filename": args.filename or Path(args.path).name}
            locs = [{"node": args.source, "path": args.path, "priority": 1, "_index": 0}]
            cached = None
        else:
            if not args.name:
                die("fetch 需要 --name（台账）或 --source/--path（直连）")
            art = cfg["artifacts"].get(args.name)
            if not art:
                report = build_failure_report(None, args.name, [], "制品未登记在台账里",
                                             cfg=cfg, dest_node=dest_node, dest_dir=dest_dir)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                _write_failure(report, dest_dir)
                return EXIT_NO_SOURCE
            art = dict(art, name=args.name)
            guard({"name": art["name"], "path": (art.get("locations") or [{}])[0].get("path", "")})
            locs = candidates(cfg, art, set(args.skip_node or []))
            cached = cache_path(cfg, art)
            cache_ok = cached.exists() and (not art.get("sha256") or sha256_file(cached) == art["sha256"])
            if cache_ok and not args.force:
                locs = [{"node": "__cache__", "path": str(cached), "priority": 0, "_index": -1}] + locs
            if not locs:
                report = build_failure_report(art, args.name, [], "台账里没有任何可用来源",
                                             cfg=cfg, dest_node=dest_node, dest_dir=dest_dir)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                _write_failure(report, dest_dir)
                return EXIT_NO_SOURCE

        staged: Path | None = None
        used: dict | None = None
        for loc in locs:
            if loc["node"] == "__cache__":
                staged = Path(loc["path"])
                attempts.append({"source_node": "local-cache", "source_path": str(staged),
                                 "result": "ok", "elapsed_s": 0.0,
                                 "sha256": art.get("sha256")})
                used = {"node": "local-cache", "path": str(staged)}
                break
            ok, info, attempt = _single_attempt(cfg, art, loc, timeout, staging)
            attempts.append(attempt)
            print(f"[{attempt['result']}] {loc['node']}:{loc['path']} ({attempt.get('elapsed_s')}s)"
                  + ("" if ok else f" -> {attempt.get('error')}"), file=sys.stderr)
            if ok:
                staged = Path(info)
                used = {"node": loc["node"], "path": loc["path"]}
                break

        if staged is None or used is None:
            report = build_failure_report(art, args.name or art.get("name"), attempts,
                                         "所有来源均失败", cfg=cfg, dest_node=dest_node, dest_dir=dest_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            _write_failure(report, dest_dir)
            return EXIT_NO_SOURCE

        digest = sha256_file(staged)
        size = staged.stat().st_size
        art_sha = digest

        # 落到本地缓存（成功即复用）
        if used["node"] != "local-cache":
            cp = cache_path(cfg, dict(art, sha256=art_sha))
            cp.parent.mkdir(parents=True, exist_ok=True)
            if not cp.exists() or sha256_file(cp) != art_sha:
                shutil.copy2(staged, cp)

        filename = art.get("filename") or Path(used["path"]).name
        record = {
            "name": art.get("name"), "project": art.get("project"), "version": art.get("version"),
            "source_node": used["node"], "source_path": used["path"],
            "destination": (f"{dest_node}:{dest_dir}" if dest_node else str(Path(dest_dir) / filename)),
            "bytes": size, "sha256": art_sha, "fetched_at": now_iso(),
        }

        if dest_node:
            node = node_spec(cfg, dest_node)
            remote_target = dest_dir.rstrip("\\/") + ("\\" if is_windows(node) else "/") + filename
            ok, err = ensure_dir(cfg, dest_node, dest_dir, timeout)
            if not ok:
                die(f"目的节点目录创建失败: {err}", EXIT_NO_SOURCE)
            ok, err = scp_push(cfg, dest_node, staged, remote_target, timeout)
            if not ok:
                die(f"推送到目的节点失败: {err}", EXIT_NO_SOURCE)
            remote_digest, herr = remote_hash(cfg, dest_node, remote_target, timeout)
            if remote_digest != art_sha:
                die(f"目的端校验失败: {herr or remote_digest} != {art_sha}", EXIT_NO_SOURCE)
            record["destination"] = f"{dest_node}:{remote_target}"
            record["destination_sha256_verified"] = True
            mok, merr = write_remote_manifest(cfg, dest_node, dest_dir, record, timeout)
            if not mok:
                print(f"ark-fetch: 警告：目的端 manifest 写入失败: {merr}", file=sys.stderr)
            # 同时在本机留一份方便审计
            write_manifest(Path(tempfile.mkdtemp(prefix="ark-mesh-audit-")), record, local=True)
        else:
            target = Path(dest_dir)
            target.mkdir(parents=True, exist_ok=True)
            dest_file = target / filename
            if dest_file.exists() and dest_file.samefile(staged) is False:
                pass
            if not dest_file.exists() or sha256_file(dest_file) != art_sha:
                shutil.copy2(staged, dest_file)
            ok, err = True, ""
            if sha256_file(dest_file) != art_sha:
                ok, err = False, "本地目的文件校验失败"
            if not ok:
                die(err, EXIT_NO_SOURCE)
            record["destination_sha256_verified"] = True
            mpath = write_manifest(target, record, local=True)
            print(f"manifest: {mpath}", file=sys.stderr)

        if args.json:
            print(json.dumps({"ok": True, "manifest_entry": record, "attempts": attempts},
                             ensure_ascii=False, indent=2))
        else:
            print(f"PASS {record['name']} {human(size)} sha256={art_sha[:16]}… "
                  f"from {record['source_node']} -> {record['destination']}")
        return EXIT_OK
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_failure_report(art: dict | None, name: str, attempts: list[dict], reason: str,
                         *, cfg: dict, dest_node: str | None, dest_dir: str) -> dict:
    next_steps = []
    if art and art.get("locations"):
        known = ", ".join(f"{l['node']}:{l['path']}" for l in art["locations"])
        next_steps.append(f"确认这些路径上的文件是否被移动/删除: {known}")
    next_steps.append("在任一同网节点用 `ark-fetch index --name ... --node ... --path ...` 登记新发现的位置")
    next_steps.append("若是新版本固件/工具，先按邮件或 NAS 取件流程落到任一节点，再登记台账")
    next_steps.append(f"全部来源失败后向派发方报 BLOCKED，并附本报告（{FAILURE_NAME}）")
    return {
        "schema": "ark-fetch-failure.v1",
        "name": name, "project": (art or {}).get("project"), "version": (art or {}).get("version"),
        "reason": reason,
        "dest_node": dest_node, "dest_dir": dest_dir,
        "attempts": attempts,
        "next_steps": next_steps,
        "generated_at": now_iso(), "config": cfg["_path"],
        "verdict": "BLOCKED",
    }


def _write_failure(report: dict, dest_dir: str) -> None:
    try:
        out = Path(dest_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / FAILURE_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    except OSError as exc:
        print(f"ark-fetch: 警告：失败报告未能落盘: {exc}", file=sys.stderr)


def cmd_archive(cfg: dict, args) -> int:
    art = cfg["artifacts"].get(args.name)
    if not art:
        die(f"制品未登记: {args.name}")
    target_node = args.to_node
    node = node_spec(cfg, target_node)
    version = args.version or art.get("version") or "unversioned"
    project = args.project or art.get("project") or "unassigned"
    filename = art.get("filename") or Path(art.get("locations", [{"path": art["name"]}])[0]["path"]).name
    base = node.get("base_dir", "/srv/storage/ark/artifacts").rstrip("\\/")
    sep = "\\" if is_windows(node) else "/"
    target_dir = sep.join([base, project, version])

    staging = Path(tempfile.mkdtemp(prefix="ark-mesh-archive-"))
    try:
        src = None
        for loc in candidates(cfg, art, set(args.skip_node or [])):
            ok, info, attempt = _single_attempt(cfg, art, loc, args.timeout, staging)
            print(f"[{attempt['result']}] {loc['node']}:{loc['path']}", file=sys.stderr)
            if ok:
                src = (Path(info), loc)
                break
        if src is None:
            die("归档失败：没有任何可用来源", EXIT_NO_SOURCE)
        staged, loc = src
        ok, err = ensure_dir(cfg, target_node, target_dir, args.timeout)
        if not ok:
            die(f"归档目录创建失败: {err}", EXIT_NO_SOURCE)
        remote_target = target_dir + sep + filename
        ok, err = scp_push(cfg, target_node, staged, remote_target, args.timeout)
        if not ok:
            die(f"归档上传失败: {err}", EXIT_NO_SOURCE)
        digest, herr = remote_hash(cfg, target_node, remote_target, args.timeout)
        if digest != sha256_file(staged):
            die(f"归档校验失败: {herr or digest}", EXIT_NO_SOURCE)
        # 登记 storage 为来源（优先级最低）
        prio = max([l.get("priority", 0) for l in art["locations"]] + [0]) + 1
        art["locations"] = [l for l in art["locations"]
                            if not (l["node"] == target_node and l["path"] == remote_target)]
        art["locations"].append({"node": target_node, "path": remote_target, "priority": prio})
        save_config(cfg)
        print(f"PASS archive {args.name} -> {target_node}:{remote_target} sha256={digest[:16]}… "
              f"(from {loc['node']})")
        return EXIT_OK
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ark-fetch", description="局域网节点间制品取件/归档")
    parser.add_argument("--config", help="来源索引路径（默认 $ARK_MESH_CONFIG 或 ~/.config/ark/mesh-sources.json）")
    subs = parser.add_subparsers(dest="cmd", required=True)

    p_status = subs.add_parser("status", help="节点可达性 + 制品台账 + 缓存")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument("--timeout", type=float, default=8.0)

    p_index = subs.add_parser("index", help="登记/更新制品来源")
    p_index.add_argument("--name", required=True)
    p_index.add_argument("--project")
    p_index.add_argument("--version")
    p_index.add_argument("--sha256")
    p_index.add_argument("--bytes", type=int)
    p_index.add_argument("--filename")
    p_index.add_argument("--note")
    p_index.add_argument("--node")
    p_index.add_argument("--path")
    p_index.add_argument("--priority", type=int)
    p_index.add_argument("--remove-node")
    p_index.add_argument("--keep-empty", action="store_true")

    p_fetch = subs.add_parser("fetch", help="取件到目的目录/节点")
    p_fetch.add_argument("--name")
    p_fetch.add_argument("--source")
    p_fetch.add_argument("--path")
    p_fetch.add_argument("--sha256")
    p_fetch.add_argument("--filename")
    p_fetch.add_argument("--dest", required=True, help="目的目录（配合 --dest-node 时是目标机路径）")
    p_fetch.add_argument("--dest-node")
    p_fetch.add_argument("--timeout", type=float, default=30.0, help="单来源超时秒数，默认 30")
    p_fetch.add_argument("--skip-node", action="append", default=[], help="临时跳过某来源（故障演练用）")
    p_fetch.add_argument("--force", action="store_true", help="忽略缓存，强制回源")
    p_fetch.add_argument("--json", action="store_true")

    p_arc = subs.add_parser("archive", help="把制品归档到 1006 存储")
    p_arc.add_argument("--name", required=True)
    p_arc.add_argument("--version")
    p_arc.add_argument("--project")
    p_arc.add_argument("--to-node", default="storage1006")
    p_arc.add_argument("--timeout", type=float, default=120.0)
    p_arc.add_argument("--skip-node", action="append", default=[])

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    try:
        return _dispatch(cfg, args)
    except MissingPass as exc:
        die(str(exc), EXIT_USAGE)


def _dispatch(cfg: dict, args) -> int:
    if args.cmd == "status":
        return cmd_status(cfg, args)
    if args.cmd == "index":
        return cmd_index(cfg, args)
    if args.cmd == "fetch":
        return cmd_fetch(cfg, args)
    if args.cmd == "archive":
        return cmd_archive(cfg, args)
    die(f"未知子命令 {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
