#!/usr/bin/env bash
# 新节点上线（Linux/macOS）：装好 ark-fetch，放好本机台账副本，跑一次自检。
# 用法： ./bootstrap.sh [--source <ark_fetch.py>] [--config <sources.json>]
#   默认从 1006 存储的 SMB/NFS 挂载点取；取不到就用 --source/--config 指定，
#   或先用 scp 把两个文件拷到本机再跑。
set -euo pipefail

SRC_TOOL="${ARK_MESH_SOURCE:-/srv/storage/ark/mesh/ark_fetch.py}"
SRC_CFG="${ARK_MESH_CONFIG_URL:-/srv/storage/ark/mesh/sources.json}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SRC_TOOL="$2"; shift 2 ;;
    --config) SRC_CFG="$2"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

ARK_DIR="$HOME/.config/ark"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ark-mesh"
mkdir -p "$ARK_DIR" "$CACHE_DIR"

TOOL="$ARK_DIR/ark_fetch.py"
CFG="$ARK_DIR/mesh-sources.json"

if [[ -f "$SRC_TOOL" && "$(readlink -f "$SRC_TOOL")" != "$(readlink -f "$TOOL" 2>/dev/null || echo "$TOOL")" ]]; then
  cp -f "$SRC_TOOL" "$TOOL"
elif [[ -f "$TOOL" ]]; then
  echo "保留已有 $TOOL"
else
  echo "MISSING: 找不到 ark_fetch.py（$SRC_TOOL），用 --source 指定" >&2
  exit 2
fi

if [[ -f "$SRC_CFG" && "$(readlink -f "$SRC_CFG")" != "$(readlink -f "$CFG" 2>/dev/null || echo "$CFG")" ]]; then
  cp -f "$SRC_CFG" "$CFG"
elif [[ -f "$CFG" ]]; then
  echo "保留已有 $CFG"
else
  echo "MISSING: 找不到台账（$SRC_CFG），用 --config 指定" >&2
  exit 2
fi

PY="$(command -v python3 || command -v python || true)"
[[ -n "$PY" ]] || { echo "MISSING: 本机没有 python3" >&2; exit 2; }

export ARK_MESH_CONFIG="$CFG"
export ARK_MESH_CACHE="$CACHE_DIR"

echo "== 本机 =="
echo "host=$(hostname) user=$(id -un) python=$PY"
echo "== 公钥（要走免密直连时追加到对端 authorized_keys） =="
if [[ -f "$HOME/.ssh/id_ed25519.pub" ]]; then
  cat "$HOME/.ssh/id_ed25519.pub"
else
  echo "(本机还没有 id_ed25519.pub，可先 ssh-keygen -t ed25519)"
fi
echo "== 自检 =="
exec "$PY" "$TOOL" status --timeout 6
