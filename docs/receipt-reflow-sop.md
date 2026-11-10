# 回执回流 SOP：执行结果 → 知识库 → 下一次调度

本文规定一次设备运行结束后如何把结果变成 `run.receipt.v1` 回执、如何回写知识库、以及下一次调度如何引用。适用于 ark-kb（知识库）与 ark-dispatch（调度）两端的日常使用。

三条硬规则，任何环节都不例外：

1. **不得把 BLOCKED / FAIL / null 改成 PASS**。证据不足时只能降级为候选回执，不能升格为通过。
2. **不得删除原始日志**。证据副本进仓库，原始产物留在执行机原位。
3. **凭据、内网地址、账号、设备编号不进回执与知识库**。需要的上下文用语义描述替代（如「办公网 NAS」「台架 A」），原始值留在本机证据目录。

## 一、回执的两档质量

| 质量 | 判定标准 | 入库后 |
|---|---|---|
| `formal` | 原始产物在**本机**、每个证据文件都能复算 SHA-256、步骤状态可逐条追溯 | 正常条目，参与调度 |
| `candidate` | 原始产物未取回、或只有扫描摘要/日志判定行；带 `evidence_gap` 说明缺什么 | `pending` + `evidence-gap` 标签，**不参与调度** |

判据只有一条：**证据能不能在本机复算**。缺完整性清单（SHA256SUMS）不算证据不足——回执哈希是转换/归档时复算的，只要在 `backfill.notes` 里写清「哈希为转换时复算，不能自证运行结束时状态」即可转正式。真正的证据不足是「产物根本不在本机」。

候选回执额外受三条约束：`result` 不得为 `pass`（只能 `needs_review` / `blocked` / `fail` / `invalid`）；必须写非空 `evidence_gap.missing`；入库必须显式加 `--allow-candidate`。

## 二、执行结束：写回执

### 2.1 落盘位置

```
docs/receipts/<YYYYMMDD-HHMMSS>-<slug>/
  run.receipt.json
  evidence/<原始文件名，保持原相对路径>
```

`run_id` 与目录同名：`run-<YYYYMMDD-HHMMSS>-<slug>`。目录名里的时间戳是该次运行的开始时间（UTC 换算前的本地时间），便于按时间排序。

### 2.2 必填字段与来源

| 字段 | 填写要求 |
|---|---|
| `task` | 一句话说明这次跑了什么，含场景与关键变量 |
| `skill` / `skill_version` | 台账登记名；台账无版本字段时填 `unregistered`，并在 `toolchain` 里补真实工具版本 |
| `node` | 执行机主机名（调度按节点做门禁） |
| `scope.device` / `project` | 与知识库既有条目保持同一写法，否则检索命中不了；`scope_key` 是 device + project + firmware |
| `result` | `pass` / `fail` / `blocked` / `invalid` / `needs_review` |
| `totals` | 计数口径写清（rounds / recognized / failed / recognition_rate） |
| `failures[]` | 每个失败项带 `name`、`round`、`reason`、`attribution`（责任层：device / bench / corpus / tool / unknown）、`evidence` |
| `responsibility[]` | 责任层判定与依据，与 `failures[].attribution` 同源 |
| `steps[]` | 逐步骤状态 pass / fail / skipped / blocked / not_run；**有 fail 的步骤不允许整体 result=pass** |
| `toolchain` | runtime、skill 版本、逐个工具版本；有哈希的（profile / bench）一并记录 |
| `firmware` | 版本来源写进 `source`（serial_boot_log / device_shell / operator / package_manifest / not_recorded）；没有二进制时 `sha256` 必须为 null，不得编造 |
| `recovery` | 是否尝试、结果、逐条动作与证据；没做就写 `attempted: false` + `not_attempted` |
| `stop_conditions` / `stop_rules` | 本次运行总结出的停止条件；引用既有条目用 `basis: kb:<id>` |
| `evidence_dir` / `evidence_sha256` | 证据目录名与非空哈希列表，两者必须对得上 |
| `evidence[]` | 结构化证据：`path`、`sha256`、`role`（summary / rounds / serial / tool_log / manifest / config / report / script / other） |
| `lessons[]` | 值得沉淀的 knowledge / method，一条一个结论 |
| `started_at` / `ended_at` | ISO-8601 UTC，带 `Z`。设备本地时间无时区时按 +08:00 换算后再写 |

### 2.3 证据的三条纪律

1. **凡进 `evidence_sha256` 的文件必须真的在 `evidence_dir` 里**，否则 `record` 直接拒绝（“evidence_sha256 与 evidence_dir 内容不匹配”）。
2. **大文件不进仓库**。1MB 级串口日志不拷贝，改由完整性清单覆盖其哈希，并在 `backfill.notes` 说明。
3. **带敏感字段的文件不拷贝**。含设备编号、账号、绝对路径的 `task_config.json` 一律不归档，只把端口、轮次、随机种子等必要参数写进回执。

## 三、回写知识库

### 3.1 导入命令

```bash
python3 tools/kb.py record --receipt docs/receipts/<dir>/run.receipt.json
python3 tools/kb.py index
python3 tools/kb.py lint
```

候选回执：

```bash
python3 tools/kb.py record --receipt <path> --allow-candidate
```

导入前建议先 `--dry-run` 看一眼会新增/合并哪些条目。

### 3.2 一次回执产出哪些条目

一份回执导入后最多产出：1 条 run 条目（执行记录）、每条 lesson 1 条 knowledge 或 method、每个 bug 1 条 bug 条目。run 条目的 claim 形如 `PASS｜任务：…｜失败 0 项，缺陷 0 项｜rounds=10,recognized=10`。

### 3.3 去重口径（为什么有时"没新增"）

- **回执级幂等**：run 条目的 `validations` 已含该 `run_id` → 直接跳过，不产生任何条目。重复导入同一份回执是安全的。
- **run 条目不做相似度合并**：同一天多场同场景运行的标题几乎一样，按相似度合并会把两次运行压成一条。run 只按 `run_id` 判重。
- **knowledge / method / bug 合并**：同类型、`scope_key`（device + project + firmware）相同、标题与结论相似度 ≥ 0.86 视为同一条，合并证据与 `validations`；`validations` 累计到 2 次时 `pending` 升 `active`。
- **候选条目永不合并、永不升 active**：带 `evidence-gap` 的条目与正式条目隔离，避免线索污染结论。

要让新结论取代旧结论，用 `--supersede <旧条目 id>`，不要直接改旧条目——旧条目是历史证据的索引，改了就对不上原始回执。

### 3.4 claim 怎么写才有用

调度的 `kb_relevance` 按设备、项目、角色关键词打分，`classify_kb` 按标签决定用途：带 `台架` / `执行通道` / `硬件` / `串口` / `声卡` 标签的 knowledge 条目会成为**前置检查**，bug 条目成为**陷阱提示**，method 条目成为**处置建议**。

因此写 lesson 时：

- 讲现象要带可识别的现场特征（串口最后一行、标记名、轮次位置），调度才能匹配到它；
- 讲归因要给出反证（例如「通过的场景里该标记同样高频出现，故不能据此归因」），避免把噪声当结论；
- 一条 lesson 只放一个结论，标题写结论本身而不是"关于 X 的分析"。

## 四、EVIDENCE_GAP 的判定与解除

### 4.1 什么情况打 EVIDENCE_GAP

- 原始产物留在执行机，本地只有摘要或扫描行；
- 只有日志判定行，没有逐轮明细；
- 结论字段与判定行冲突，需人工核对。

不要因为"没有完整性清单"就打缺口（见第一节）。也不要因为"结果不好看"打缺口——FAIL 是完整结论，不是缺口。

### 4.2 缺口怎么写

```json
"evidence_gap": {
  "code": "EVIDENCE_GAP",
  "missing": ["原始运行产物（cases.csv / results.csv / tool.log 未取回本机）", "运行目录的完整性清单"],
  "reason": "历史运行只留下远程扫描行，原始证据未归档到本机，哈希无法复算。",
  "blocking": true
}
```

`missing` 必须逐项写清缺哪份文件、缺到什么程度，让人能照着补。

### 4.3 如何解除

1. 从执行机取回 `missing` 里列的产物，放进 `evidence/`；
2. 复算哈希，写进 `evidence_sha256` 与 `evidence[]`；
3. 删掉 `evidence_gap`，把 `quality` 改为 `formal`（或删掉该字段）；
4. 重跑 `record`（此时是同一 `run_id`，会被幂等拦下）——**正确做法是把旧候选条目 `--supersede` 掉，再用补齐后的正式回执入库**；
5. `index` + `lint`，确认候选条目的 `evidence-gap` 标签已随 supersede 消失。

## 五、下一次调度如何引用

### 5.1 派发前：先查，再写请求

```bash
python3 tools/kb.py query --device "<设备串>" --top 20
python3 tools/kb.py query --capability <能力名> --top 20
```

请求里 `device.model`、`device.project`、`bench.node` 三个字段决定知识命中：`scope.device` 等于 node 或 model、出现在任务描述里、或 `project` 互相包含，条目才会被认为与本次任务相关（`kb_scope_linked`）。请求写得含糊，知识库就等于空的。

### 5.2 生成计划并核对引用

```bash
python3 scripts/dispatch.py plan --request request.json --out plan.json --kb <ark-kb 路径>
python3 scripts/dispatch.py check --plan plan.json
```

必须核对三处：

- `plan.preconditions` 里出现带 `（kb:<id>）` 的条目——说明历史教训已进入前置检查；
- `plan.recovery` 的每步有 `basis: kb:<id>`，端口解析正确，`reset_allowed=false` 时为空；
- `plan.stop_rules` 的 `source=kb` 条目有 `basis: kb:<id>`，且引用的 id 确实在 `plan.sources` 里。

带 `evidence-gap` 的候选条目不会出现在 `plan.kb` 里——它们被调度端主动过滤，只作线索。若发现某条历史教训"没进计划"，先查它是不是候选条目、`scope` 写法是否与请求对得上。

### 5.3 执行中：按 stop_rules 收手

`stop_rules` 不是建议，是停止条件。命中即停止、保留现场、按 `recovery` 处置；`recovery` 的 `verify` 不通过不得继续后续轮次。

## 六、刷新知识库后的完整回归

改完条目（导入、supersede、手工修订）后固定跑这四步：

```bash
python3 tools/kb.py index                 # 索引必须重建，否则 lint 报 index 漂移
python3 tools/kb.py lint                  # 0 错误才算合格；警告逐条确认
python3 tools/kb.py query --device "<设备串>" --top 20   # 新条目能被检索到
python3 scripts/dispatch.py plan ... && python3 scripts/dispatch.py check --plan ...
```

`lint` 的警告要分清两类：既有条目的「证据文件不在本机」是历史事实（证据在远端机器，按路径 + 哈希登记），可以长期存在；`evidence-gap` 提示是待办，补齐证据后应消失。

## 七、发布前检查清单

- [ ] 回执 `check_receipt` 通过，`evidence_sha256` 每项都能在 `evidence_dir` 里复算命中
- [ ] `result` 与 `steps` 不矛盾（有 fail 步骤就不可能是 pass）
- [ ] `started_at` / `ended_at` 为 UTC 带 `Z`，且结束不早于开始
- [ ] 证据副本里没有内网地址、账号、口令、token、设备编号
- [ ] 回执 `quality` 与证据实际位置一致（本机可复算 = formal，否则 candidate + gap）
- [ ] 导入后 `lint` 0 错误，新条目可在三个视角检索到
- [ ] `dispatch.py plan` + `check` 通过，新条目出现在前置检查 / recovery / stop_rules 的 `basis` 里
- [ ] 候选条目没有混进 `plan.kb`

## 八、常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 回执导入报「evidence_sha256 与 evidence_dir 内容不匹配」 | 哈希列表里有文件不在 `evidence_dir` | 要么把文件拷进来，要么从 `evidence_sha256` 删掉 |
| 候选回执报「不得为 pass」 | 证据不足却给了通过结论 | 改成 `needs_review` / `blocked`，或补齐证据转正式 |
| 二次导入提示「已入库，跳过」 | 回执级幂等 | 正常行为；要改内容请先 supersede 旧条目 |
| 两次同场景运行只剩一条记录 | 历史版本按相似度合并了 run | 已修正为 run 只按 `run_id` 判重；旧数据需人工拆分 |
| `query` 看不到刚导入的条目 | 默认 `--top 5`，pending 条目排在 active 之后 | 加 `--top 20` 再看 |
| 计划里没有历史教训 | `scope` 写法与请求对不上，或条目是候选 | 核对 `device` / `project` 字符串，确认条目不带 `evidence-gap` |
| `lint` 报 index 漂移 | 改了条目没重建索引 | 跑 `kb.py index` |
