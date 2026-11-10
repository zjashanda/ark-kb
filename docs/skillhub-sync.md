# SkillHub 同步与节点 skill 版本清单

本文件定义 NoahsArk 工作区「云端 skill → 节点本地 skillhub」的可复核同步流程，以及节点智能体必须遵守的工作区约定。

- 机器可读清单：[`registry/skill-sync-manifest.json`](../registry/skill-sync-manifest.json)
- 节点台账：[`registry/nodes.json`](../registry/nodes.json)
- 能力台账：[`registry/skills.json`](../registry/skills.json)（35 个 GitHub skill）

## 1. 目录约定（硬规则）

| 用途 | 路径 | 规则 |
|---|---|---|
| skill 源码 | `<workspace>/skillhub`（Windows `D:\zhsh\workspace\skillhub`，Linux `~/zhsh/workspace/skillhub`） | 只读来源；由同步工具写入，任务不得就地改 |
| 任务结果 | `<workspace>/tasks/<task-id>` | 任务的脚本、日志、证据、报告全部落这里 |
| 镜像与检出 | `<hub>/cache/<skill>.git`（裸镜像）、`<hub>/<skill>`（检出） | 同步工具维护 |
| 废弃副本 | `<hub>/<skill>.broken-<ts>-<hash>` | 只报不删，永不覆盖 |

禁止：把任务的临时文件、日志、模型产物写进 `skillhub/`；禁止删除节点上的 skill；禁止对检出做 `reset --hard` / `clean` / `checkout --`。

## 2. 工具

### 2.1 控制节点（bszT14）：`tools/skill_sync.py`

```bash
# 1) 采集 35 个 skill 的远端 SHA（控制节点用 SSH 别名访问 GitHub）
python3 tools/skill_sync.py remote-shas --registry registry/skills.json --out /tmp/remote-shas.json

# 2) 汇总各节点 inventory → manifest
python3 tools/skill_sync.py assemble --registry registry/skills.json \
  --nodes registry/nodes.json --remote /tmp/remote-shas.json \
  --inventory <node1.json> --inventory <node2.json> \
  [--applied /tmp/apply.json] --out registry/skill-sync-manifest.json

# 3) 控制节点本地 hub 安全快进（默认 dry-run）
python3 tools/skill_sync.py apply --hub ~/zhsh/workspace/skillhub \
  --remote-base git@github-zjashanda:zjashanda [--apply]
```

`--applied` 只作用于产生它的那个 hub（按 `hub` 路径比对），不会把一台机器的同步结果算到别的机器头上。

### 2.2 节点侧：`tools/skillhub_bootstrap.ps1` / `tools/skillhub_bootstrap.sh`

只依赖 git，用于「任务开始前只同步本任务需要的 skill」。

```powershell
# Windows：只读清点
powershell -NoProfile -ExecutionPolicy Bypass -File skillhub_bootstrap.ps1 -Hub "D:\zhsh\workspace\skillhub" -Inventory -Json
# Windows：按需同步（默认 dry-run）
powershell -NoProfile -ExecutionPolicy Bypass -File skillhub_bootstrap.ps1 -Hub "D:\zhsh\workspace\skillhub" -Skills "Polaris,lstest" [-Apply] [-Json] [-RemoteBase https://github.com/zjashanda]
```

```bash
# Linux
bash skillhub_bootstrap.sh --hub ~/zhsh/workspace/skillhub --inventory --json
bash skillhub_bootstrap.sh --hub ~/zhsh/workspace/skillhub --skills Polaris,lstest [--apply] [--json] [--remote-base git@github-zjashanda:zjashanda]
```

动作语义：`CLONE`（新建镜像+检出）、`PULL`（干净检出快进）、`SKIP_IN_SYNC`、`OUTDATED`（dry-run 报告可快进）、`SKIP_DRIFT`（有本地修改/分叉，拒绝写）、`ABSENT`、`ERROR`（私有库无凭据、网络不可达）。
`--fail-on-drift` 返回 8，`--fail-on-remote` 返回 3，便于任务前置检查直接失败。

## 3. 状态定义

| 状态 | 含义 | 是否自动写 |
|---|---|---|
| `IN_SYNC` | 本地 SHA = 远端 SHA 且无跟踪文件改动 | 否 |
| `OUTDATED` | 本地落后远端且可快进 | 是（`apply`/`--apply`） |
| `UPDATED` | 本次运行已完成快进 | — |
| `LOCAL_DRIFT` | 有跟踪文件改动，或本地与远端分叉 | **否**，只报告 |
| `UNMANAGED_COPY` | 目录存在但不是 git 检出，无法比对版本 | 否 |
| `MISSING_CHECKOUT` | 只有 cache 镜像，没有检出 | 否（需显式建） |
| `PRIVATE_SKILL` | 现场私有 skill（不在 35 个 GitHub skill 内） | 否 |
| `REMOTE_UNREACHABLE` | 该节点无法解析远端 SHA（私有库无凭据 / 网络不可达） | 否 |
| `ARCHIVED` | 台账标记 archived 且本地干净（归档能力仍在节点上） | 否 |
| `ABSENT` | 该节点 hub 里没有这个 skill | 否 |

判定优先级（高→低）：`UNMANAGED_COPY` → `LOCAL_DRIFT` → `MISSING_CHECKOUT` → `REMOTE_UNREACHABLE` → `ARCHIVED` → `IN_SYNC`/`OUTDATED`；无条目记 `ABSENT`。
**本地可观测事实永远先于远端与归档状态**——断网或"已归档"都不能掩盖本地被改过的事实。

## 4. 每任务 bootstrap 流程

1. 任务开始：`-Inventory -Json` 取本节点现状（只读）。
2. 从任务需要的 skill 列表（通常来自 issue 描述）取子集，**只同步这些**，不全量复制 35 个。
3. `-Skills <a,b>` 先 dry-run 看 `OUTDATED`/`SKIP_DRIFT`/`ERROR`；确认后加 `-Apply`。
4. 出现 `SKIP_DRIFT`：不要覆盖，改为在 `tasks/<task-id>` 里复制一份改，或先与负责人确认改动归属。
5. 任务结束：结果只写 `tasks/<task-id>`，`skillhub` 保持与远端一致。

## 5. 2026-11-10 首次实测

12 个节点、35 个 GitHub skill，共 420 个节点×skill 组合（另加 1 个现场私有 skill）：

| 节点 | 端点 | 系统 | hub | 实测状态 |
|---|---|---|---|---|
| bszT14 | 10.11.63.42:22 | Linux | `/home/bszheng/zhsh/workspace/skillhub` | `UPDATED=1`（Polaris 4dbb82c→a4ef614）、`LOCAL_DRIFT=1`（listenai-laid-installer 5 处改动）、`ABSENT=33` |
| pvm1005 | 10.11.63.24:10026 | Windows | `D:\zhsh\workspace\skillhub` | `PRIVATE_SKILL=1`（tcl-device-autoburn）、`ABSENT=35` |
| PVM1003 | 10.11.63.24:10023 | Windows | 同上 | `ABSENT=35` |
| win008 | 10.11.63.24:10024 | Windows | 同上 | `ABSENT=35` |
| win000 | 10.11.63.36:22 | Windows | 同上 | `OUTDATED=1`（Polaris 4dbb82c，落后 a4ef614）、`ABSENT=34` |
| win002 / win003 / win004 / win005 / win006 / win010 | 见 `registry/nodes.json` | Windows | 同上 | `ABSENT=35` |
| test-101 | 10.11.63.24:10022 | Linux | `/home/testadmin/zhsh/workspace/skillhub` | `ABSENT=35` |

合计：`ABSENT=417`、`UPDATED=1`、`LOCAL_DRIFT=1`、`OUTDATED=1`、`PRIVATE_SKILL=1`。

结论：**节点 skillhub 目前基本是空的**，不是"版本旧"而是"没铺开"；先把清单固化，再按任务按需铺。

### 网络可达性实测（决定同步方向）

| 位置 | GitHub 访问 | 实测 |
|---|---|---|
| bszT14（控制节点） | SSH 别名 `github-zjashanda`（ssh.github.com:443） | 35/35 成功；**HTTPS 443 直连失败** |
| win000 | HTTPS | 单次 `ls-remote` 偶发成功，连续 3 次与 clone 全部超时/重置 |
| test-101 | HTTPS | `ls-remote` 成功；私有库提示需要凭据 |

因此当前默认策略：**控制节点取数、节点按需取公开库**。私有库（`a4m-Jenkins`、`fileball`、`qw-email-handle`、`zhsh`）在节点侧一律记 `REMOTE_UNREACHABLE`，要铺开必须先做节点级 git 凭据（属于单独的授权项，不在本流程内自动执行）。

## 6. 智能体指令（粘贴到节点工作区 AGENTS.md）

```markdown
## SkillHub 工作区约定（NOAH-40）

- skill 源码只在 `workspace/skillhub`（Windows `D:\zhsh\workspace\skillhub`，Linux `~/zhsh/workspace/skillhub`），由同步工具维护，任务**不得就地修改**。
- 任务产物（脚本、日志、证据、报告）只写 `workspace/tasks/<task-id>`，禁止写进 `skillhub/`。
- 任务开始前只同步本任务需要的 skill：
  Windows `powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\tools\skillhub_bootstrap.ps1 -Hub D:\zhsh\workspace\skillhub -Skills <a,b>`
  Linux   `bash <repo>/tools/skillhub_bootstrap.sh --hub ~/zhsh/workspace/skillhub --skills <a,b>`
  先不加 `-Apply` 看报告，确认无 `SKIP_DRIFT` 再加。
- 见到 `SKIP_DRIFT`：不要覆盖，不要在 `skillhub` 里改，复制到 `tasks/<task-id>` 里改并说明原因。
- 不要删除节点上的 skill、不要 `reset --hard`、不要动 `*.broken-*`。
```

## 7. 回滚

- 同步只做 fast-forward，回滚即 `git -C <checkout> reset --hard <记录在 manifest 的 local_sha>`（需人工确认后进行）。
- 本次 `bszT14/Polaris` 的 `local_sha`=4dbb82c3d55484464acbf9e96ab35f512f2fe2d5，`to_sha`=a4ef61478f343e599282ba3aac4cc8705fbdae4a，均在 manifest 中留档。
- 工具不产生删除动作，因此没有"恢复被删文件"的需求。
