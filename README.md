# ark-kb

方舟知识库 v1：把每次执行沉淀成下次能命中的经验。

公开仓库，只写可公开的事实、方法与缺陷记录；**不写凭据、不写内网地址清单、不把大文件塞进仓库**。

## 里面有什么

| 类型 | 内容 | 例子 |
|---|---|---|
| `knowledge` | 事实：串口默认波特率、日志特征、协议字段、设备构成 | “TCL 设备是双 MCU，麦克风 8 通道 UAC” |
| `method` | 方法：归因思路、判定红线、断言设计、证据组织 | “BLOCKED 不得写成 PASS” |
| `run` | 单次执行记录：任务、结果、失败数、证据引用 | 一次巡检或一轮验证的回执摘要 |
| `bug` | 已知缺陷与规避办法，必须能对上固件/版本 | 某固件下唤醒丢轮 |

每条都必须有证据：`run_id`、文件路径 + sha256、commit 或 issue 编号。没有证据的结论不进库。

## 目录

```
ark-kb/
  README.md
  schema/
    receipt.v1.json      # 执行回执契约
    entry.v1.json        # 知识条目 schema
    index.v1.json        # 索引格式
    asset-entry.v1.json  # TTS 资产索引条目（只存元数据，不存音频）
  entries/
    knowledge/entries.jsonl
    method/entries.jsonl
    run/entries.jsonl
    bug/entries.jsonl
    asset/entries.jsonl  # TTS 资产可搜索索引（真源在 asset-tools）
  index/                 # 由 kb.py 生成，不要手改
    by-device.json
    by-capability.json
    by-skill.json
    asset-index.json     # 资产索引（voice/language/engine 分桶）
  tools/
    kb.py                # record / query / lint / sync / index
    secret_scan.py       # 复用 skill-git 的凭据规则
    ark_receipt.py       # 归档后的 manifest+summary → run.receipt.v1
    ark-receipt.sh       # 节点侧入口（Linux）：生成回执并回传到 receipts/
    ark-receipt.ps1      # 节点侧入口（Windows PowerShell 5.1），同一契约
  tests/                 # 离线单测 + 测试替身
  docs/
    acceptance-v1.md     # v1 验收记录
    seed-sources.md      # 首批条目的来源
    tts-library-index.md # TTS 资产索引边界与用法
    receipts/            # 真实回执与证据（只放小文本）
```

`registry/skills.json` 由能力台账（P0-a）产出后合入本仓库；本仓库不另存一份台账。

## 快速开始

要求 Python 3.10+，不需要第三方包。凭据扫描器来自 `skill-git` 仓库：

```bash
export SKILL_GIT_HOME=~/.codex/skills/skill-git   # 或用 --skill-git-home
```

### 1. 回执入库

```bash
python3 tools/kb.py record --receipt docs/receipts/20261106-kb-selftest/run.receipt.json
```

- 校验 `schema/receipt.v1.json`、时间顺序、`evidence_dir` 与 `evidence_sha256`。
- 在本机能找到 `evidence_dir` 时逐个比对哈希；找不到时降级为“路径 + 哈希”登记并告警。
- 命中凭据规则直接拒绝；找不到扫描器同样拒绝（见“安全”）。
- 生成 1 条 `run` 条目 + 每条 lesson 1 条 `knowledge`/`method` 条目 + 每条 bug 1 条 `bug` 条目，初始 `pending`。
- 回执可带 `tags`（顶层、lesson、bug 三处均可），会原样落到条目上；`query --capability` 只认条目 tags / 台账能力词，英文能力名（如 `wake-recognition`）必须由回执 tags 带下来，否则入库后仍查不到。
- 同一 `run_id` 重复入库会被跳过（幂等）。

### 2. 检索

```bash
python3 tools/kb.py query --device win009 --top 5
python3 tools/kb.py query --device TCL-DUT --capability 录音 --json
python3 tools/kb.py query --skill lstts --include-stale
```

只返回标题、结论摘要与证据引用，**不返回全文**。默认不返回 `stale` / `superseded`，需要时加 `--include-stale`。

命中会给条目的 `hits += 1` 并回写；只读检出或并发查询用 `--no-hit-count`。

### 3. TTS 资产索引

```bash
python3 tools/kb.py asset-record --asset manifest.json --json
python3 tools/kb.py asset-query --voice 付小春 --language ZH --json
```

只登记已发布资产的搜索元数据（asset ID、cache key、SHA、作用域、受控相对路径、摘要），
不存音频与文本全文；命中只是线索，取件仍由 `asset-tools tts-library fetch/verify` 负责。
详见 `docs/tts-library-index.md`。

### 4. 校验

```bash
python3 tools/kb.py lint              # 有问题退出码 3
python3 tools/kb.py lint --strict     # 告警也算失败
```

校验内容：schema、重复 id、证据完整性、证据文件哈希、`superseded_by` 指向、索引是否漂移、同一 `run_id` 重复入库、台账登记情况、过期提示、凭据规则。

### 5. 同步

```bash
python3 tools/kb.py sync                     # fetch + pull --rebase（默认 main）
python3 tools/kb.py sync --push              # 只推当前功能分支
```

`--push` 拒绝推 `main` / `master`、拒绝有未提交改动的分支。合并由人批准。

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（lint 允许有警告） |
| 3 | 校验失败 / 拒绝写入 / 拒绝推送 |

## 回执契约 `run.receipt.v1`

必填：`run_id`、`task`、`skill`、`skill_version`、`scope{device,project,firmware}`、`result`、`totals`、`failures[]`、`bugs_found[]`、`evidence_dir`、`evidence_sha256[]`、`lessons[]`、`confidence`、`started_at`、`ended_at`。

- `result` 只允许 `pass | fail | blocked | invalid | needs_review`。
- `evidence_dir` 相对回执文件所在目录（或绝对路径），否则无法定位。归档到存储服务器的回执照样写 `/srv/storage/ark/results/<node>/<project>/<run_id>`：本机没有这个目录时按回执里的 `evidence_files[]` 逐文件登记「路径 + 哈希」，`verified=false`；没有 `evidence_files` 则退化成一条 `run` 级证据。
- `evidence_sha256` 至少一条，每条 64 位小写十六进制。
- `lessons[]` 的 `type` 只有 `knowledge` 与 `method`，一条 lesson 一条条目。
- 执行方只写本机文件，不需要网络；大文件（日志、音频）只登记路径与哈希。

示例：`docs/receipts/20261106-kb-selftest/run.receipt.json`（本机证据）、`docs/receipts/20261102-win009-wake/run.receipt.json`（存储服务器证据）。归档与入库全流程见 `docs/result-archive.md`。

## 条目 `entry.v1`

| 字段 | 说明 |
|---|---|
| `id` | `kb-<type>-<12hex>`，由 type + scope + title + claim 决定 |
| `type` | `knowledge / method / run / bug` |
| `scope` | `device / project / firmware / platform`，可为 null |
| `title` / `claim` | 标题与一句话结论（检索只返回这两个） |
| `evidence[]` | `{kind, ref, sha256?, verified?, note?}`，`kind` 见下 |
| `confidence` | `high / medium / low` |
| `status` | `pending / active / stale / superseded` |
| `superseded_by` | 冲突时指向新条目，旧条目保留 |
| `source_skill` | 产出该条目的 skill 名；人工整理可为 null |
| `created` / `updated` | ISO-8601 |
| `hits` | 检索命中次数 |
| `validations[]` | 独立验证过该结论的 run_id |

证据 `kind`：`run`（回执/执行）、`file`（仓库内文件 + sha256）、`commit`（`repo@sha`）、`issue`（Multica issue 编号）、`url`（公开链接）。

## 治理规则

- **去重**：同 type、同 scope，标题与结论的综合相似度 ≥ 0.86 时合并；证据取并集，`validations` 取并集。
- **升级**：同一结论被 ≥2 个独立 run 验证（`validations` 长度 ≥2）→ `pending` 升 `active`；`stale` 收到新验证时先回 `pending`。
- **冲突**：不删旧条目。用 `record --supersede <旧 id>` 把旧条目标 `superseded` 并指向新条目，两条并存。
- **过期**：固件淘汰或 90 天零命中 → 标 `stale`；`lint` 会提示，检索默认不返回。
- **命中计数**：`query` 命中后 `hits += 1`，作为保留/淘汰依据。

## 与能力台账的关系

- 默认读 `registry/skills.json`，也可用 `--registry` 指定。
- 台账缺失时**降级告警**（跳过 skill 名校验），不会静默通过；`--strict` 下未登记 skill 记错误。台账当前在 main 的 `registry/skills.json`（`725d3f4`）。
- `--capability` 查询会用台账里该 skill 的能力描述扩展关键词。
- 索引只依赖条目自身（tags、scope、skill），不依赖台账，避免两笔 PR 合并顺序造成索引漂移。改台账后跑一次 `kb.py index` 即可。

## 安全

- 扫描规则唯一来源：`skill-git/scripts/skill_assets.py` 的 `SECRET_PATTERNS`。本仓库不复制规则。
- 找不到扫描器 → `record`/`lint` 退出码 3；只有显式 `--allow-missing-scanner` 才降级（仅离线自检）。
- 命中时只报规则序号和文件路径，**不回显明文**。
- 不写账号、token、私钥、序列号、具体内网地址；网段只写语义（“台架所在网段无路由”）。
- 日志与音频只存路径和 sha256；仓库内只放小体积文本证据。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

73 条用例，全程离线（sync 用本地 bare 仓库），覆盖全部子命令与治理规则。

## v1 的已知限制

- 能力台账已在 main（`725d3f4`）；台账文件被删或路径不对时，lint 只给“台账缺失”告警，不会静默通过。
- 自检条目里的 `source_skill` 仍是历史名 `skill-kb`；台账主名已改为 `ark-kb`（NOAH-55 补录），两者不一致时 lint 会告警，属已知项。
- 索引与条目写入是整文件重写，多人并发写需要先拉取；不是并发数据库。
- 目前只验证工具链，不代表任何真机结论；真机结论必须来自对应回执。
