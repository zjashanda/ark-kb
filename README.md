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
  entries/
    knowledge/entries.jsonl
    method/entries.jsonl
    run/entries.jsonl
    bug/entries.jsonl
  index/                 # 由 kb.py 生成，不要手改
    by-device.json
    by-capability.json
    by-skill.json
  tools/
    kb.py                # record / query / lint / sync / index
    backfill.py          # 历史结果 → 回执的确定性转换器（scan / build / rows / selftest）
    secret_scan.py       # 复用 skill-git 的凭据规则
  tests/                 # 离线单测 + 测试替身
  docs/
    acceptance-v1.md     # v1 验收记录
    seed-sources.md      # 首批条目的来源
    receipt-reflow-sop.md # 执行结果 → 知识库 → 下一次调度的回流 SOP
    receipts/            # 真实回执与证据（只放小文本）
    reports/             # 回填转换清单、扫描汇总、导入报告
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
- **`run` 条目只按 `run_id` 判重，不走相似度合并**：同一天多场同场景运行的标题几乎相同，合并会把两次运行压成一条；`knowledge` / `method` / `bug` 仍按 0.86 相似度合并。
- **候选回执默认拒收**：`quality: candidate` 必须带 `evidence_gap.missing`、`result` 不得为 `pass`；确需沉淀线索要显式加 `--allow-candidate`，入库后是 `pending` + `evidence-gap` 标签，永不升 `active`，也不进入调度依据。

### 2. 检索

```bash
python3 tools/kb.py query --device win009 --top 5
python3 tools/kb.py query --device TCL-DUT --capability 录音 --json
python3 tools/kb.py query --skill lstts --include-stale
```

只返回标题、结论摘要与证据引用，**不返回全文**。默认不返回 `stale` / `superseded`，需要时加 `--include-stale`。

命中会给条目的 `hits += 1` 并回写；只读检出或并发查询用 `--no-hit-count`。

### 3. 校验

```bash
python3 tools/kb.py lint              # 有问题退出码 3
python3 tools/kb.py lint --strict     # 告警也算失败
```

校验内容：schema、重复 id、证据完整性、证据文件哈希、`superseded_by` 指向、索引是否漂移、同一 `run_id` 重复入库、台账登记情况、过期提示、凭据规则。

### 4. 同步

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
- `evidence_dir` 相对回执文件所在目录（或绝对路径），否则无法定位。
- `evidence_sha256` 至少一条，每条 64 位小写十六进制。
- `lessons[]` 的 `type` 只有 `knowledge` 与 `method`，一条 lesson 一条条目。
- 执行方只写本机文件，不需要网络；大文件（日志、音频）只登记路径与哈希。

### 可选字段（v1.1 增补，全部向后兼容）

必填集合没变，老回执照常入库；下列字段用于把“证据完整性、责任层、恢复与停止条件”写进回执，供调度直接消费。

| 字段 | 用途 |
|---|---|
| `node` | 执行节点（台架所在机器），调度按节点做门禁；缺省时入库映射到 `scope.platform` |
| `quality` | `formal`（默认）或 `candidate`；候选必须带 `evidence_gap` 且 `result != pass` |
| `steps[]` | 逐步骤 `n / name / status(pass,fail,skipped,blocked,not_run) / evidence[]`；有 fail 步骤时整体不得为 pass |
| `responsibility[]` | 责任层：`layer(device,bench,corpus,tool,unknown)` + `note` + `evidence[]` |
| `toolchain` | `runtime`、skill 名与版本、逐个 `tools[{name,version,sha256}]` |
| `firmware` | `version`、`sha256`（没有二进制必须为 null）、`source`（serial_boot_log / device_shell / operator / package_manifest / not_recorded） |
| `recovery` | `attempted`、`result(recovered,not_recovered,not_attempted,partial)`、`actions[]`、`evidence[]` |
| `stop_conditions[]` / `stop_rules[]` | 本次总结出的停止条件；引用既有条目用 `basis: kb:<id>` |
| `evidence[]` | 结构化证据：`path`、`sha256`、`role(summary,rounds,serial,tool_log,manifest,config,report,script,other)`、`verified`；哈希必须同时出现在 `evidence_sha256` |
| `evidence_gap` | `code: EVIDENCE_GAP`、`missing[]`、`reason`、`blocking`，仅候选回执可用 |
| `backfill` | 回填元数据：`tool`、`version`、`source_kind`、`source_path`、`converted_at`、`sanitised`、`notes[]` |

示例：`docs/receipts/20261106-kb-selftest/run.receipt.json`（完整字段）、`docs/receipts/20261104-144020-tcl003-indextts-10cmd/run.receipt.json`（真实崩溃运行）、`docs/receipts/20261014-163403-win009-wake-interval/run.receipt.json`（候选回执）。

### 历史结果回填

```bash
python3 tools/backfill.py scan   --source <debugdata 目录>
python3 tools/backfill.py build  --source <debugdata> --out docs/receipts --reports docs/reports/<日期>-receipt-backfill
python3 tools/backfill.py rows   --scan <远程巡检 out 目录> --out docs/receipts --reports docs/reports/<日期>-receipt-backfill
python3 tools/backfill.py selftest
```

`build` 把本机原始运行目录转成正式回执（本机可复算哈希），`rows` 把只有扫描摘要的远程运行转成候选回执并输出逐行台账与分桶统计。两类输出都写进 `conversion-list.csv`，按 source 去重，可重复执行。

回流流程、候选解除办法与调度引用规则见 `docs/receipt-reflow-sop.md`。

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

- **去重**：同 type、同 scope，标题与结论的综合相似度 ≥ 0.86 时合并；证据取并集，`validations` 取并集。`run` 条目例外——只按 `run_id` 判重，不做相似度合并。
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

21 条用例，全程离线（sync 用本地 bare 仓库），覆盖四条命令与治理规则。

## v1 的已知限制

- 能力台账已在 main（`725d3f4`）；台账文件被删或路径不对时，lint 只给“台账缺失”告警，不会静默通过。
- `skill-kb` 自身尚未出现在 35 仓台账里，自检条目的 `source_skill` 会持续告警。
- 索引与条目写入是整文件重写，多人并发写需要先拉取；不是并发数据库。
- 目前只验证工具链，不代表任何真机结论；真机结论必须来自对应回执。
