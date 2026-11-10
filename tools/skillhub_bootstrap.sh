#!/usr/bin/env bash
# skillhub_bootstrap.sh - NoahsArk 节点侧 skillhub 清单与按需同步（Linux）
#
# 用法：
#   bash skillhub_bootstrap.sh --hub /path/to/skillhub --inventory --json
#   bash skillhub_bootstrap.sh --hub /path/to/skillhub --skills Polaris,lstest [--apply] [--json]
#
# 只依赖 bash + git。默认 dry-run；--apply 才写盘。
# 硬规则：不删除、不 reset --hard、不 clean、不碰 *.broken-*、不写 <hub>/tasks、不交互提问。
set -u

GIT_TERMINAL_PROMPT=0
GIT_PAGER=cat
PAGER=cat
export GIT_TERMINAL_PROMPT GIT_PAGER PAGER
export GIT_ASKPASS=/bin/true SSH_ASKPASS=/bin/true

hub=""
skills=""
remote_base="${SKILLHUB_REMOTE_BASE:-https://github.com/zjashanda}"
mode="inventory"
apply=0
json=0
fail_on_drift=0
fail_on_remote=0

usage() {
  echo "usage: $0 --hub PATH (--inventory | --skills a,b) [--apply] [--json] [--remote-base BASE] [--fail-on-drift] [--fail-on-remote]" >&2
}

# 远端地址模板：默认公开 HTTPS；离线节点可用 SSH 别名，例 git@github-zjashanda:zjashanda
remote_url() { printf '%s/%s.git' "$remote_base" "$1"; }

# 带超时的 git 包装（无 timeout 命令时退化为直连）
run_git() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 180 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 -c credential.helper= "$@"
  else
    git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 -c credential.helper= "$@"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --hub) hub="${2:-}"; shift 2 ;;
    --remote-base) remote_base="${2:-}"; shift 2 ;;
    --inventory) mode="inventory"; shift ;;
    --skills) skills="${2:-}"; mode="bootstrap"; shift 2 ;;
    --apply) apply=1; shift ;;
    --json) json=1; shift ;;
    --fail-on-drift) fail_on_drift=1; shift ;;
    --fail-on-remote) fail_on_remote=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$hub" ]; then usage; exit 2; fi

now() { date +"%Y-%m-%dT%H:%M:%S%:z"; }
node_name() { hostname 2>/dev/null || echo unknown; }

# JSON 字符串转义（skill 名与路径只含安全字符，这里仍做最小转义）
jesc() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

git_head() { git -C "$1" rev-parse --verify --quiet HEAD 2>/dev/null || true; }
git_branch() { git -C "$1" branch --show-current 2>/dev/null || true; }
count_lines() { printf '%s' "$1" | grep -c . 2>/dev/null || true; }
tracked_dirty() { git -C "$1" status --porcelain --untracked-files=no 2>/dev/null; }
all_changes() { git -C "$1" status --porcelain --untracked-files=all 2>/dev/null; }

is_git_dir() { [ -e "$1/.git" ] || [ -d "$1/.git" ]; }

# ---------- inventory ----------
inv_names=(); inv_kinds=(); inv_paths=(); inv_gits=(); inv_branches=(); inv_shas=(); inv_caches=(); inv_dirty=(); inv_untracked=()

add_entry() { # name kind path git branch sha cache_sha dirty untracked
  inv_names+=("$1"); inv_kinds+=("$2"); inv_paths+=("$3"); inv_gits+=("$4")
  inv_branches+=("$5"); inv_shas+=("$6"); inv_caches+=("$7"); inv_dirty+=("$8"); inv_untracked+=("$9")
}

# 裸镜像：HEAD 可能是 unborn，依次回退到 origin/main、origin/HEAD
bare_sha() {
  local c="$1" s
  s="$(git -C "$c" rev-parse --verify --quiet HEAD 2>/dev/null || true)"
  [ -n "$s" ] || s="$(git -C "$c" rev-parse --verify --quiet refs/remotes/origin/main 2>/dev/null || true)"
  [ -n "$s" ] || s="$(git -C "$c" rev-parse --verify --quiet refs/remotes/origin/HEAD 2>/dev/null || true)"
  printf '%s' "$s"
}

cache_sha_of() {
  local c="$hub/cache/$1.git"
  if [ -d "$c" ]; then bare_sha "$c"; fi
}

describe_git_dir() { # dir -> sets D_BRANCH D_SHA D_DIRTY D_UNTRACKED
  D_BRANCH=""; D_SHA=""; D_DIRTY=0; D_UNTRACKED=0
  D_BRANCH="$(git_branch "$1")"
  D_SHA="$(git_head "$1")"
  local td all
  td="$(tracked_dirty "$1")"
  all="$(all_changes "$1")"
  D_DIRTY=$(printf '%s' "$td" | grep -c . || true)
  local ac
  ac=$(printf '%s' "$all" | grep -c . || true)
  D_UNTRACKED=$(( ac - D_DIRTY ))
  [ "$D_UNTRACKED" -lt 0 ] && D_UNTRACKED=0
}

run_inventory() {
  if [ ! -d "$hub" ]; then
    if [ "$json" = 1 ]; then
      printf '{"schema":"skillhub-inventory.v1","node":"%s","os":"linux","hub":"%s","generated_at":"%s","entries":[],"error":"hub not found"}\n' \
        "$(jesc "$(node_name)")" "$(jesc "$hub")" "$(now)"
    else
      echo "hub not found: $hub" >&2
    fi
    return 0
  fi

  # cache mirrors
  for c in "$hub"/cache/*.git; do
    [ -d "$c" ] || continue
    local name cs
    name="$(basename "$c" .git)"
    cs="$(bare_sha "$c")"
    add_entry "$name" "cache" "$c" true "" "$cs" "$cs" 0 0
  done

  # worktrees
  for d in "$hub"/worktrees/*; do
    [ -d "$d" ] || continue
    local name
    name="$(basename "$d")"
    if is_git_dir "$d"; then
      describe_git_dir "$d"
      add_entry "$name" "worktree" "$d" true "$D_BRANCH" "$D_SHA" "$(cache_sha_of "$name")" "$D_DIRTY" "$D_UNTRACKED"
    else
      add_entry "$name" "worktree" "$d" false "" "" "$(cache_sha_of "$name")" 0 0
    fi
  done

  # legacy checkouts + broken copies at hub root
  for d in "$hub"/*; do
    [ -d "$d" ] || continue
    local name
    name="$(basename "$d")"
    case "$name" in
      cache|worktrees) continue ;;
    esac
    case "$name" in
      *.broken-*)
        if is_git_dir "$d"; then
          describe_git_dir "$d"
          add_entry "$name" "other" "$d" true "$D_BRANCH" "$D_SHA" "" "$D_DIRTY" "$D_UNTRACKED"
        else
          add_entry "$name" "other" "$d" false "" "" "" 0 0
        fi
        continue ;;
    esac
    if is_git_dir "$d"; then
      describe_git_dir "$d"
      add_entry "$name" "checkout" "$d" true "$D_BRANCH" "$D_SHA" "$(cache_sha_of "$name")" "$D_DIRTY" "$D_UNTRACKED"
    else
      add_entry "$name" "checkout" "$d" false "" "" "$(cache_sha_of "$name")" 0 0
    fi
  done

  # 稳定输出：按 kind 优先级 + name 排序
  local idx order
  order=$(for i in "${!inv_names[@]}"; do printf '%s\t%s\t%s\n' "${inv_kinds[$i]}" "${inv_names[$i]}" "$i"; done | sort -k1,1 -k2,2 | cut -f3)

  if [ "$json" = 1 ]; then
    local out="" first=1 i n
    for i in $order; do
      n=$(jesc "${inv_names[$i]}")
      [ "$first" = 1 ] || out="$out,"
      first=0
      out="$out{\"name\":\"$n\",\"kind\":\"${inv_kinds[$i]}\",\"path\":\"$(jesc "${inv_paths[$i]}")\",\"git\":${inv_gits[$i]},\"branch\":\"$(jesc "${inv_branches[$i]}")\",\"sha\":\"${inv_shas[$i]}\",\"cache_sha\":\"${inv_caches[$i]}\",\"dirty_tracked\":${inv_dirty[$i]},\"untracked\":${inv_untracked[$i]}}"
    done
    printf '{"schema":"skillhub-inventory.v1","node":"%s","os":"linux","hub":"%s","generated_at":"%s","entries":[%s]}\n' \
      "$(jesc "$(node_name)")" "$(jesc "$hub")" "$(now)" "$out"
  else
    for i in $order; do
      printf '%-10s %-28s git=%-5s sha=%.8s dirty=%s untracked=%s\n' \
        "${inv_kinds[$i]}" "${inv_names[$i]}" "${inv_gits[$i]}" "${inv_shas[$i]:-}" "${inv_dirty[$i]}" "${inv_untracked[$i]}"
    done
  fi
}

# ---------- bootstrap ----------
bs_names=(); bs_actions=(); bs_from=(); bs_to=(); bs_details=()

add_result() { # name action from to detail
  bs_names+=("$1"); bs_actions+=("$2"); bs_from+=("$3"); bs_to+=("$4"); bs_details+=("$5")
}

remote_sha_of_cache() { # cache -> sha
  local c="$1" s
  s="$(git -C "$c" rev-parse --verify --quiet refs/remotes/origin/main 2>/dev/null || true)"
  if [ -z "$s" ]; then s="$(git -C "$c" rev-parse --verify --quiet refs/remotes/origin/HEAD 2>/dev/null || true)"; fi
  printf '%s' "$s"
}

first_line() { printf '%s' "$1" | sed -n '1p' | cut -c1-200; }

sync_one() {
  local name="$1"
  local cache="$hub/cache/$name.git"
  local co=""

  if is_git_dir "$hub/$name"; then co="$hub/$name"
  elif is_git_dir "$hub/worktrees/$name"; then co="$hub/worktrees/$name"; fi

  if [ ! -d "$cache" ] && [ -z "$co" ]; then
    if [ "$apply" = 1 ]; then
      mkdir -p "$hub/cache" 2>/dev/null
      if ! git init --bare --quiet "$cache" 2>/dev/null; then
        add_result "$name" "ERROR" "" "" "git init --bare failed"
        return
      fi
      git -C "$cache" remote add origin "$(remote_url "$name")" 2>/dev/null
    else
      add_result "$name" "ABSENT" "" "" "no cache and no checkout"
      return
    fi
  fi

  if [ -d "$cache" ]; then
    local ferr
    ferr="$(run_git -C "$cache" fetch --prune --quiet origin '+refs/heads/*:refs/remotes/origin/*' 2>&1)"
    if [ $? -ne 0 ]; then
      add_result "$name" "ERROR" "" "" "$(first_line "$ferr")"
      return
    fi
  fi

  local rsha
  rsha="$(remote_sha_of_cache "$cache")"
  if [ -z "$rsha" ]; then
    add_result "$name" "ERROR" "" "" "cannot resolve remote sha (private repo or no branch)"
    return
  fi

  if [ -z "$co" ]; then
    if [ "$apply" = 1 ]; then
      co="$hub/$name"
      local cerr
      cerr="$(run_git clone --quiet "$cache" "$co" 2>&1)"
      if [ $? -ne 0 ]; then
        add_result "$name" "ERROR" "" "" "$(first_line "$cerr")"
        return
      fi
      git -C "$co" remote set-url origin "$(remote_url "$name")" 2>/dev/null
      cerr="$(git -C "$co" checkout --quiet -B main "$rsha" 2>&1)"
      if [ $? -ne 0 ]; then
        add_result "$name" "ERROR" "" "$rsha" "$(first_line "$cerr")"
        return
      fi
      add_result "$name" "CLONE" "" "$rsha" "cloned from cache"
      return
    else
      add_result "$name" "ABSENT" "" "$rsha" "cache only"
      return
    fi
  fi

  local lsha td
  lsha="$(git_head "$co")"
  td="$(tracked_dirty "$co")"
  if [ -n "$td" ]; then
    add_result "$name" "SKIP_DRIFT" "$lsha" "$rsha" "tracked changes present"
    return
  fi

  if [ "$lsha" = "$rsha" ]; then
    add_result "$name" "SKIP_IN_SYNC" "$lsha" "$rsha" ""
    return
  fi

  if git -C "$co" merge-base --is-ancestor "$lsha" "$rsha" 2>/dev/null; then
    if [ "$apply" = 1 ]; then
      local merr
      merr="$(git -C "$co" merge --ff-only --quiet "$rsha" 2>&1)"
      if [ $? -ne 0 ]; then
        add_result "$name" "ERROR" "$lsha" "$rsha" "$(first_line "$merr")"
        return
      fi
      add_result "$name" "PULL" "$lsha" "$rsha" "fast-forward"
    else
      add_result "$name" "OUTDATED" "$lsha" "$rsha" "fast-forward available"
    fi
    return
  fi

  if git -C "$co" merge-base --is-ancestor "$rsha" "$lsha" 2>/dev/null; then
    add_result "$name" "AHEAD" "$lsha" "$rsha" "local ahead of origin"
    return
  fi

  add_result "$name" "SKIP_DRIFT" "$lsha" "$rsha" "diverged"
}

run_bootstrap() {
  if [ ! -d "$hub" ] && [ "$apply" = 1 ]; then mkdir -p "$hub" 2>/dev/null; fi
  local IFS=','
  local name
  for name in $skills; do
    name="$(printf '%s' "$name" | tr -d '[:space:]')"
    [ -n "$name" ] || continue
    sync_one "$name"
  done

  local drift=0 remote_err=0 i
  for i in "${!bs_actions[@]}"; do
    case "${bs_actions[$i]}" in
      SKIP_DRIFT) drift=1 ;;
      ERROR) remote_err=1 ;;
    esac
  done

  if [ "$json" = 1 ]; then
    local out="" first=1
    for i in "${!bs_actions[@]}"; do
      [ "$first" = 1 ] || out="$out,"
      first=0
      out="$out{\"name\":\"$(jesc "${bs_names[$i]}")\",\"action\":\"${bs_actions[$i]}\",\"from_sha\":\"${bs_from[$i]}\",\"to_sha\":\"${bs_to[$i]}\",\"detail\":\"$(jesc "${bs_details[$i]}")\"}"
    done
    local ap="false"; [ "$apply" = 1 ] && ap="true"
    printf '{"schema":"skillhub-bootstrap.v1","hub":"%s","remote_base":"%s","apply":%s,"generated_at":"%s","entries":[%s]}\n' \
      "$(jesc "$hub")" "$(jesc "$remote_base")" "$ap" "$(now)" "$out"
  else
    for i in "${!bs_actions[@]}"; do
      printf '%-13s %-28s %s -> %s  %s\n' "${bs_actions[$i]}" "${bs_names[$i]}" "${bs_from[$i]:0:8}" "${bs_to[$i]:0:8}" "${bs_details[$i]}"
    done
  fi

  local rc=0
  [ "$fail_on_drift" = 1 ] && [ "$drift" = 1 ] && rc=8
  [ "$rc" = 0 ] && [ "$fail_on_remote" = 1 ] && [ "$remote_err" = 1 ] && rc=3
  return $rc
}

if [ "$mode" = "inventory" ]; then
  run_inventory
else
  run_bootstrap
fi
