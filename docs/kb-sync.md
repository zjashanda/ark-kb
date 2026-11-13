# 知识同步契约 v2：事件驱动检查点与多作用域

本文是 ark-kb 对 NOAH-66 提案 **v2.0.0** 的落地说明，取代 v1 的「任务结束一次性回流」。
v2 的核心变化只有一句：**回流挂在生命周期事件上，不挂在任务正常结束上**；任务失败、被阻断、
崩溃、取消，都必须先落检查点，再异步归档入库。字段名以 `schema/checkpoint.v1.json` 为准，
本文不另立名字。

入口仍然只有一个：`tools/kb.py`。新增 `checkpoint`、`outbox`、`promote` 三个子命令，
`record` 增 `--checkpoint`，其余子命令的行为与退出码不变。

## 1. 为什么不再等任务结束

end-only 回流有三个必然缺口：

- 失败路径没有知识：`BLOCKED` / `FAIL` / 中断的任务结束时不写回执，最有价值的排障知识直接丢失；
- 崩溃没有留痕：进程被杀时内存里的现象、尝试序列、证据路径全部蒸发；
- 归档与入库强耦合：一旦归档失败，整条回流链断在最后一步，前面所有证据白攒。

v2 把顺序改成「先落盘、后归档、再入库」：任务目录里的 WAL 是唯一事实源，归档与入库都是
可以失败重试的下游动作。任务结束只做聚合、质量提升与 outbox 关闭，不再产生新知识。

## 2. 事件驱动触发矩阵

`trigger` 是封闭枚举，只有下表这些取值；表外的值 schema 直接拒绝。

| 触发 | 何时写 | quality 判定 | 是否产出新知识 |
|---|---|---|---|
| `EXECUTION_CHECK` | 预检完成后立即 | 只记环境/能力/输入版本/kb 基线 → `formal` | 元数据，不含结论 |
| `STAGE_FINISHED` | 每个阶段结束（PASS 或 FAIL） | 证据完整 ⇒ `formal` | 是 |
| `BLOCKED` | 立即写，不等任务结束 | 现象 + attempts + 证据齐全 ⇒ `formal`（bug/method） | 是 |
| `FAIL` | 立即写，不等任务结束 | 同上，缺证据降 `candidate` | 是 |
| `NEEDS_REVIEW` | 立即写 | 同上 | 是（待复核） |
| `WATCHDOG_RUNNING_NO_EVIDENCE` | watchdog 判定即写 | 由最后一个已落盘事件推得 ⇒ `candidate` | 否，仅提示 |
| `WATCHDOG_STATE_DRIFT` | watchdog 判定即写 | 同上 ⇒ `candidate` | 否，仅提示 |
| `WATCHDOG_TIMEOUT` | watchdog 判定即写 | 同上 ⇒ `candidate` | 否，仅提示 |
| `WATCHDOG_HEARTBEAT_LOST` | watchdog 判定即写 | 同上 ⇒ `candidate` | 否，仅提示 |
| `MANUAL_CANCEL` | 取消时，或下一次 run 扫描 WAL 补写 | 证据不完整 ⇒ `candidate` | 否 |
| `RUNTIME_CRASH` | 恢复器或下一次 run 扫描 WAL 时补写 | 完全无证据 ⇒ `evidence_gap` | 否 |
| `RECOVERY_REPLAY` | 下一次 run 启动时 | 不新建语义条目，只补发未完成 outbox | 否 |
| `FINAL_RECEIPT` | 任务收尾 | 只聚合、提升质量、关闭 outbox | 否 |

`FINAL_RECEIPT` 明确不产生新知识：它把前面各检查点的结论聚合起来，把 `candidate` 在证据补齐后
升成 `formal`，把 outbox 关闭。指望它兜底补写前面漏掉的阶段知识是不成立的。

## 3. append-only WAL 与 outbox 恢复

落盘位置（全部在任务目录内，不进知识库仓库）：

```text
receipts/outbox/checkpoints-YYYYMMDD.jsonl   # 追加写，永不改写、永不删除
receipts/outbox/outbox.json                  # checkpoint_id → 状态，可重建
receipts/outbox/archived/<id>.json           # 归档成功后的副本
```

- WAL 只追加：一次事件一行 JSON，日期取自事件的 `at`；同一事件重复提交由幂等键挡住。
- `outbox.json` 是索引，不是事实源：它丢了、写坏了，用 `outbox --replay` 从 WAL 重建。
- 归档或入库失败只更新 outbox 状态与 `retry`，不碰 WAL；重试从 WAL 重放，事件本身不丢。

命令：

```bash
# 校验事件并追加（schema 不合法退出 2，重复事件打印 duplicate 并退出 0）
python3 tools/kb.py checkpoint --root . --outbox receipts/outbox \
  --event receipts/outbox/events/stage-15.json --json

# 查看未关闭项；--replay 从 WAL 补写 outbox.json 缺失的行（不改 WAL）
python3 tools/kb.py outbox --root . --outbox receipts/outbox --status pending
python3 tools/kb.py outbox --root . --outbox receipts/outbox --replay --json
```

`outbox --replay` 是崩溃恢复的唯一手段：进程在「写完 WAL、未写索引」之间死掉时，索引少一行，
WAL 多一行，replay 把差集补回索引并报告补了几条。它永远不改 WAL，所以可以反复执行。

## 4. 幂等键：同一事件只入一次

```text
evidence_digest = sha256(join(sorted(evidence[].sha256), "\n"))   # 无证据时 sha256("")
checkpoint_id   = sha256(issue_id|run_id|stage|event_seq|evidence_digest)
```

要点：

- `issue_id + run_id + stage + event_seq` 定位「第几个阶段的第几件事」，`evidence_digest` 定位
  「证据集合本身」；证据变了就是另一件事，证据没变就是同一件事。
- `evidence_digest` 只对证据哈希排序后拼接，与证据顺序无关，换顺序不会产生新 id。
- 无证据事件的 `evidence_digest` 取空串哈希，不会与「有证据但为空」混淆。
- 同一 id 再次提交：不新增 WAL 行、不新建条目、不重复入库，直接返回已有状态。

## 5. 质量分层：失败也可以是 formal

| 情形 | 层 | 能否回流 | 能否驱动 dispatch |
|---|---|---|---|
| 正常阶段、证据完整 | `formal` | 是 | 是 |
| 失败但有现象、attempts、证据完整 | `formal`（type=bug/method） | 是 | 是，作为恢复建议 / stop rule |
| 进程崩溃、证据不完整 | `candidate` | 否，仅提示 | 否 |
| 只有推测、完全无证据 | `evidence_gap` | 否 | 否 |

失败知识可以 `formal`，这是 v2 与 v1 最大的口径差异：一次干净复现的 `FAIL` 比一次顺利的 `PASS`
更有价值。但 `formal` 不等于 `PASS`——失败事件的 outcome 永远写 `FAIL` / `BLOCKED` /
`NEEDS_REVIEW`，不得为了让门禁变绿而改写成 `PASS`。

质量提升不是覆盖：后续 run 补齐证据后，新条目承接结论，旧条目 `status=superseded`、
`superseded_by` 指向新条目、`lineage[]` 记录追溯链。**永不删除历史。**

## 6. 作用域层级与查询叠加

作用域由近到远：

```text
run → node / bench → project → device_family / platform → capability → global
```

每个检查点与条目都必须说明自己属于哪一层：`scope.level`（封闭七值）+ `scope.key`，
可选 `scope.parent` 指向上层 key。查询按「近者优先」叠加：

1. 先取 `run` / `node` / `project` 的精确命中；
2. 再继承 `device_family` / `platform` / `capability` / `global`；
3. 按 canonical id 去重，保留来源层级与优先级；
4. 同 id 冲突时近层不能覆盖远层事实，只能追加 `exceptions`（每条必须带 `reason`）；
5. 每条结果都要能写出 `kb:<entry_id>@<commit>` 来源，供 dispatch 写入 `sources[]`。

项目层影响更广层事实的唯一合法方式就是例外：

```json
{"level": "project", "key": "TCL",
 "derived_from": ["kb-knowledge-0123456789ab"],
 "exceptions": [{"rule": "烧录前必须先断电", "reason": "TCL 硬件版本上电烧录会锁死"}]}
```

`query --project B` 时，A 的 `exceptions` 条目被排除；只有查询 A 才生效。没有这条隔离，
一个项目的土办法会污染所有项目的结论。

## 7. canonical 条目 vs 项目引用

- 共同内容只存一条 canonical 条目（`scope_level` 为 `capability` 或 `global`）；
- 项目条目用 `derived_from` 指向 canonical 条目，用 `applies_to` 列出适用项目，
  用 `exceptions` 记录本项目差异；**不复制正文**，避免同一结论散落成孤岛；
- `lineage[]` 记录结论演进链，`checkpoint_ids[]` 记录该条目由哪些检查点产出。

`record --checkpoint <id>` 会把生成或合并的条目都挂上该 checkpoint id；id 不在 WAL 里时直接
拒绝（退出 2），防止「条目引用了不存在的事件」这种无法追溯的脏数据。

## 8. 提升与降级

提升（promotion）只看证据，不看主观感觉：同一结论在至少两个项目验证通过、且没有项目专属字段
（无 `exceptions`、无 `scope.device` / `scope.firmware`）时，才成为提升候选：

```bash
python3 tools/kb.py promote --root . --min-projects 2
python3 tools/kb.py promote --root . --min-projects 2 --out receipts/promote.json --json
```

`promote` 是只读的：默认只打印候选，**不写文件、不改条目、不自动提升**；给 `--out` 才写报告。
报告每项是 `{entry_id, promote_to, projects[], reason}`，`promote_to` 只能取 `capability` 或
`global`。真正的提升仍要人工审核证据后改条目，工具不做静默晋升。

降级（demotion）发生在发现反例时：给条目加 `applies_to` 限定适用范围，或补 `exceptions` 说明
差异，绝不删除历史条目。错误的旧结论保留为 `superseded`，比假装没发生过更有价值。

## 9. candidate 永不驱动 dispatch

只有同时满足三件事的条目可以驱动 `preflight` / `recovery` / `stop_rules`：

- 质量层是 `formal`；
- 状态不是 `stale` / `superseded`；
- 适用范围与本次 `scope` 匹配。

`candidate` 只能作为提示出现，消费侧必须标 `needs_confirmation`；`evidence_gap` 连提示都不算。
拿候选结论做停机判据，等于让猜测去关设备电源。

## 10. 每个检查点单独 query-back

per-checkpoint query-back 是 v2 的硬要求：每个 checkpoint ingest 之后，用与入库相同的维度再查
一次，确认新条目出现在默认 top 20，并把结果写回该检查点的 `kb_query_back_status`。

中断允许留 `pending`，但必须在 outbox 里可恢复；下一次 run 用 `outbox --replay` 续上。
跨节点暂不可见时记 `deferred` 并在 `retry.last_error` 写原因，不得伪造 `pass`。

```bash
python3 tools/kb.py query-back --root . --delivery receipts/delivery.json --top 20 --json
```

## 11. outbox 关闭条件

一个检查点只有同时满足下面三条才算关闭：

```text
archive_status        = ok
kb_ingest_status      ∈ {recorded, skipped_no_kb}
kb_query_back_status  ∈ {pass, deferred(带原因)}
```

`outbox --status pending` 列出的就是未关闭项。全部关闭前，`FINAL_RECEIPT` 只能写
`NEEDS_REVIEW`，不得写 `PASS`。工具只负责如实报告，不替任务改状态。

## 12. 内容边界

ark-kb 只收：脱敏摘要、索引、sha256、受控资产位置。禁止收：凭据、原始敏感日志、
超过 1 MiB 的大文件正文（只登记路径与哈希）。检查点证据项只有 `path` / `sha256` / `bytes`
三个字段，天然不承载正文。回执入库前跑凭据扫描，命中就整份拒绝，不做「事后清洗」。

## 13. 跨项目共享测试（自动化）

共享能力必须有自动化用例兜底，`tests/test_kb_sync.py` 已覆盖：

1. 项目 A 产出 capability 知识后，项目 B 用同维度查询能命中该 canonical 条目；
2. A 的项目 `exceptions` 不出现在 B 的查询结果里；
3. `candidate` 不进 `formal` 消费集合，也不出现在 dispatch 可用结果中。

用例全部在临时目录里复制 schema/entries/registry 后运行，不触碰仓库真实的
`entries/`、`index/`、`receipts/`。

## 14. 命令速查

```bash
# 1. 阶段结束：先落检查点（WAL 追加 + outbox 索引）
python3 tools/kb.py checkpoint --root . --outbox receipts/outbox --event event.json --json

# 2. 条目回流并挂到检查点
python3 tools/kb.py record --root . --receipt receipts/run.receipt.json \
  --delivery-out receipts/delivery.json --checkpoint <checkpoint_id>

# 3. 回查 + 关闭 outbox
python3 tools/kb.py query-back --root . --delivery receipts/delivery.json --top 20 --json
python3 tools/kb.py outbox --root . --replay --json

# 4. 跨项目提升候选（只读）
python3 tools/kb.py promote --root . --min-projects 2 --json
```

## 15. 自检

```bash
python3 -m unittest discover -s tests -q
python3 tools/secret_scan.py .
```

契约文件必须过时间契约检查：时间字段只用北京时间 `YYYY-MM-DD HH:MM:SS`，空格分隔、秒精度，
不出现其他分隔符、时区后缀、数字偏移与小数秒。检查点与 outbox 里的时间同样如此。
