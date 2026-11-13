# 知识回流（reflow）的准入判据

本文件说明 ark-kb 在接受一次结果回流时，如何被 NoahsArk 执行门禁约束。门禁完整规则见 NOAH-66 的
`gate-plan-integration.md`（下称「整合规则」），本文只覆盖知识这一片：哪一层回执可以回流、回流前
回执必须满足什么、`run_id` 幂等、索引与能力台账的只读边界、以及拒绝回流时怎么留证。

回流入口是 `tools/kb.py record`。它只读回执与证据，不改归档目录，也不改能力台账。

## 1. 只有正式回执可以回流

整合规则 §7.2 把回执分三层，`kb.py record` 只认第一层：

| 层 | 位置 | 能否回流 | 原因 |
|---|---|---|---|
| 正式 `formal` | `receipts/run.receipt.json` | 可以 | 合约全字段，`evidence_sha256` 可核 |
| 候选 `candidate` | `receipts/candidates/<name>.json` | 不可以 | 结论未复核，或证据只覆盖部分场景 |
| 证据缺口 `evidence-gap` | `receipts/evidence-gaps/<name>.json` | 不可以 | 缺的是证据，不是结论 |

`candidate` 与 `evidence-gap` 不能伪装成正式回执送入 `record`：`record` 按 `receipt.v1` 校验字段，
缺 `evidence_sha256`、缺 `result`、时间不合契约都会直接拒绝。想要入库，先把候选结论补齐证据、
在任务目录重生成正式回执，再走一次 `record`。

## 2. 回流前回执必须满足的字段条件

`check_receipt` 用 `schema/receipt.v1.json` 做第一道校验，随后逐项核对：

| 字段 | 准入要求 | 不满足时 |
|---|---|---|
| `run_id` | 非空，且与归档目录名一致 | 拒绝入库；无法关联「哪一次 run」 |
| `result` | 属于 `pass` / `fail` / `blocked` / `invalid` / `needs_review` | schema 拒绝；未知结果必须先在归档侧归一 |
| `evidence_sha256` | 非空数组，每项 64 位小写十六进制 | 拒绝入库，`$ .evidence_sha256: 至少需要一个文件哈希` |
| `confidence` | `high` / `medium` / `low` | schema 拒绝；`low` 的回执可以入库，但条目不会被当成已验证结论 |
| `started_at` / `ended_at` | `YYYY-MM-DD HH:MM:SS`，北京时间，**不带时区标记** | schema 时间正则拒绝；`ended_at` 早于 `started_at` 也拒绝 |
| `evidence_dir` | 非空 | 拒绝入库 |

时间口径与 [time-contract.md](time-contract.md) 一致：不写 `T` 分隔符、不写时区后缀、不写小数秒。
回执的时间格式来自 `lib/ark_time.py` 的单一实现，`kb.py` 只解析不重写。

`evidence_sha256` 与 `evidence_dir` 的配合是这套准入的核心：

- 证据目录在本机：逐文件重算哈希，`evidence_sha256` 里有任何一个对不上就 `KBError` 拒绝入库；
- 证据目录不在本机（存储型证据）：按「路径 + 哈希」登记，`verified=false`，并发出一条警告。
  这是预期形态，不当作失败。

## 3. `run_id` 幂等

`record` 在写任何条目之前先做一次幂等判定：

1. 读全部条目，找 `type == run` 且 `validations` 里已含本次 `run_id` 的条目；
2. 命中即打印「回执 `<run_id>` 已入库，跳过（record 幂等）」并返回 `0`；
3. 未命中才生成候选条目、合并重复、写条目与索引。

因此**同一份回执重复 record 不会产生重复条目**，也不会把 `hits`、`validations` 再涨一轮。
反过来，想把修正后的结论写进去，必须用新的 `run_id` 重跑并归档，不能用同名回执覆盖旧条目——
这层约束保证知识库里的每条结论都能追到一次真实 run。

## 4. 索引与能力台账的只读安全

- `index/by-device.json`、`index/by-capability.json`、`index/by-skill.json` 是 `entries/` 的派生视图，
  只由 `save_indexes()` 在 `record` 成功落盘时整文件重写，不手工编辑。
- `registry/skills.json`（能力台账）在整个回流链路里**只读**：`record` 只用来校验回执的 `skill`
  是否登记、条目 `source_skill` 是否可解析。台账里没有的 skill 产生警告，条目仍以 `pending` 入库；
  台账永远不会被 `record` 写。
- `query` 只回写命中条目的 `hits`，不重写索引，也不碰台账。索引漂移由 `lint` 报错，不靠 `query` 修。
- 索引键只依赖条目自身字段，不用台账派生词扩展；跨仓库合并顺序不会让索引自己漂移。

这条边界让回流可以安全重放：最坏情况是条目文件被整文件重写回同一内容，台账与索引结构不变。

## 5. 拒绝回流与缺口留证

以下情形一律**拒绝回流**，并把缺口写进任务目录，而不是"再试一次直到通过"：

| 情形 | 处理 |
|---|---|
| `evidence_sha256` 与 `evidence_dir` 内容不符 | 抛 `KBError`，不写任何条目；缺口记入 `receipts/evidence-gaps/` |
| 回执 schema 校验失败 | 拒绝入库；先修归档侧回执，再重新 record |
| 时间不合契约或 `ended_at < started_at` | 拒绝入库；按时间契约重生成回执 |
| 回执命中凭据规则 | 拒绝写入公开仓库；凭据只能在命令层避免，不能事后清洗 |
| 传入的是 candidate / evidence-gap | 拒绝；先补齐证据生成正式回执 |

缺口记录要写清三件事：缺哪个文件的哈希、预期值、补齐方式；对应条目在 `FINAL_RECEIPT.open_items[]`
里逐条点名。归档侧据此追加新的 `STAGE_FINISHED`，不修改旧事件。

**回流不是验收。** `record` 返回 `0` 只说明条目已写入，不代表结论已被采纳；issue 的 `done`
仍然只有人可以置位，智能体最多把状态推到 `in_review`（整合规则 §3.1）。
