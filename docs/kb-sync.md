# 知识同步契约：读、写、回流确认

本文定义 NoahsArk 任务与 ark-kb 之间的知识同步契约，是 NOAH-66 提案在 ark-kb 这一仓的落地说明。
它管三件事：开工前怎么查、收工后怎么入库、入库后怎么确认真的查得到。字段名以
`schema/kb-context.v1.json` 与 `schema/delivery.v1.json` 为准，本文不另立名字。

入口只有一个：`tools/kb.py`。`record` 负责回流，`query` 负责检索，`query-back` 负责回查。

## 1. 固定顺序，不可颠倒

```text
evidence manifest → run.receipt.json → ark-archive 归档(ok) → ark-kb record → ark-kb query-back
```

任何一步跳过，交付判 `DELIVERY_INCOMPLETE`。这条顺序有三个硬约束：

- 归档只复制不移动，源目录永远保留；
- 回执只生成不覆盖，`run.receipt.json` 是这一轮唯一的正式回执；
- 入库先于回查，`query-back` 的输入就是 `record` 写出的条目 id。

`record` 自己不调归档、不改归档目录；它只读回执与证据。归档状态由 ark-archive 写入并回传，
`record` 只负责把它带进 delivery 回执里，不替归档做判断。

## 2. 两个契约，各写在哪

### 2.1 读侧 `ark.kb-context.v1`

写在两处：

- 任务目录 `plan.md` 的 `## 知识查询` 段，给人看；
- `run.receipt.json` 的可选顶层字段 `kb_context`，给机器读。

必填字段：`schema`、`contract_version`、`queried_at`、`dims`、`registry_commit`、`hits`、
`no_hit`、`refresh_points`、`refresh_log`。`dims` 必须同时给
`capability / project / device / firmware / profile / skill`；`hits[]` 每条要带
`id / type / status / confidence / score / commit / source_skill`。

`queried_at` 与 `refresh_log[].at` 统一写北京时间 `YYYY-MM-DD HH:MM:SS`：空格分隔、秒精度、
不带时区标记。schema 用正则锁死这个形状，写错就校验失败，不给下游猜的机会。

空结果不是错误，记 `no_hit=true` 即可。取不到知识库提交号时 `registry_commit` 写 `unknown`，
不许编一个看起来像哈希的值。

### 2.2 写侧 `ark.delivery.v1`

落在 `receipts/delivery.json`，并复制一份进 `run.receipt.json` 的可选顶层字段 `delivery`。

必填字段：`schema`、`run_id`、`idempotency_key`、`archive_status`、`kb_ingest_status`、
`kb_entry_ids`、`kb_query_back_status`、`retry`、`updated_at`。四个状态位的取值是封闭的：

| 状态位 | 取值 |
|---|---|
| `archive_status` | `pending` / `ok` / `failed` / `skipped` |
| `kb_ingest_status` | `pending` / `recorded` / `skipped_no_kb` / `failed` |
| `kb_query_back_status` | `pending` / `pass` / `fail` / `deferred` |
| `kb_entry_ids` | 字符串数组，`record` 写回 |

可选字段：`archive_manifest_sha256`、`kb_query_back_at`、`kb_query_back_hits`、`no_kb_reason`。

`tools/kb.py record --delivery-out <path>` 写这个文件。写之前会先读旧文件，只补默认值与本次字段，
不删除别的字段；`record` 还顺手把本次回执的维度写进 `dims`，让 `query-back` 能复用同一组条件。

## 3. 四类结果都要回执

`PASS / FAIL / BLOCKED / NEEDS_REVIEW` 四种结果都必须生成回执，也都要走知识回流判定。
没有知识价值时，不是"不写"，而是显式写 `kb_ingest_status=skipped_no_kb` 并给出 `no_kb_reason`：

- `no-new-knowledge`：与既有结论重复，没有新增事实；
- `pure-inventory`：只做清点，不产出可复用知识；
- `duplicate-of-existing:<entry_id>`：已知条目的再次验证，复用旧 id；
- `sensitive-not-indexable`：含敏感信息，只登记位置，不写内容。

这四类是封闭集合，`record --no-kb-required` 必须配一个，否则按用法错误退出 2，并且不写任何条目。
理由很直白：静默跳过会让"没知识"和"忘了回流"看起来一样，审计时无法区分。

## 4. 完成门禁：四个状态位同时成立

允许判 PASS 的组合只有两种：

```text
archive_status=ok 且 kb_ingest_status=recorded 且 kb_query_back_status=pass
archive_status=ok 且 kb_ingest_status=skipped_no_kb 且 no_kb_reason 非空
```

其余组合一律 `DELIVERY_INCOMPLETE`，`FINAL_RECEIPT` 只能写 `NEEDS_REVIEW`，不得写 PASS。
注意这是"允许 PASS"的必要条件，不是充分条件：任务本身的验收结论仍然独立判定。

## 5. 分层：formal / candidate / evidence-gap

| 层 | 位置 | 可回流 | 可否驱动 dispatch |
|---|---|---|---|
| formal | `receipts/run.receipt.json` | 是 | 是（需 active 且证据完整） |
| candidate | `receipts/candidates/` | 否 | 否 |
| evidence-gap | `receipts/evidence-gaps/` | 否 | 否 |

`record` 只认传给它的那一份正式回执，不遍历 `candidates/`，也不读取 `evidence-gaps/`。
候选结论与证据缺口永远不能进入 `steps[]`、`recovery[]`、`stop_rules[]`——它们没有被复核，
拿它们做失败恢复或停机判据，等于让猜测驱动设备。想入库就补证据、在任务目录重生成正式回执。

## 6. 幂等：同一个 run 重放不新增条目

`idempotency_key = sha256(scope + run_id)`，写进 delivery 回执。`record` 在写任何条目之前先看
条目里有没有 `type=run` 且 `validations` 已含本次 `run_id` 的条目：

- 命中：打印"已入库，跳过（record 幂等）"，退出 0，条目与索引都不动；
- 未命中：生成候选条目，再用 `find_duplicate()` 与既有条目比对，命中就复用旧 id。

重复导入同一 run 不新建条目，只累加 `hits` 与 `validations`：`hits` 由 `query` 计数，
`validations` 由 `merge_entry()` 去重追加。也就是说，重复回流最多让证据与验证记录更厚，
不会让知识库长出两条同义结论。

`query-back` 同样幂等：它只读条目、不写 `hits`，重复执行得到相同结论。

## 7. 生命周期与 superseded_by

条目状态固定四段：`pending → active → stale → superseded`。

- 新条目一律 `pending`，等第二次独立验证后自动升 `active`；
- 长期零命中、超过 `STALE_DAYS` 的条目应标 `stale`，`lint` 会提示；
- 结论被新证据推翻时，用 `record --supersede <old_id>` 把旧条目标 `superseded`，
  并把 `superseded_by` 指向本次生成的新条目；
- `query` 默认排除 `stale` 与 `superseded`，要看得显式加 `--include-stale`。

旧条目永不删除：冲突不是靠覆盖解决，而是靠 `superseded_by` 留出结论演进链。

## 8. 失败重试与跨节点可见性

入库或回查失败时最多重试 3 次，按指数退避 1 / 2 / 4 分钟，每次把尝试次数与最后错误写进
`retry.attempts`、`retry.last_error`。重试只针对可恢复错误，schema 不符、凭据命中、证据哈希
不符这类问题重试多少次都没用，直接 `failed` 并留证。

跨节点不可见是另一种情况：条目写进了别的节点，本节点暂时查不到。此时 `query-back` 记
`deferred`，原因写进 `retry.last_error`，并上报 `WATCH_DELIVERY_INCOMPLETE`。`deferred` 与
`fail` 一样不满足 PASS 条件，绝不能伪造 `pass` 来"让它绿"。

## 9. 内容边界

ark-kb 只收：脱敏摘要、索引、`sha256`、受控资产位置。禁止收：凭据、原始敏感日志、
超过 1 MiB 的大文件正文（只登记路径与哈希）。回执入库前会跑凭据扫描，命中就整份拒绝，
不做"事后清洗"——清洗过的凭据仍然泄露过。

## 10. 命令速查

```bash
# 开工前查询并留痕（结果写 plan.md 的「知识查询」段）
python3 tools/kb.py query --root . --device bench-a --capability wake-recognition --json

# 收工回流：写条目 + 写 delivery 回执
python3 tools/kb.py record --root . --receipt receipts/run.receipt.json \
  --delivery-out receipts/delivery.json

# 无知识价值：不写条目，只记理由
python3 tools/kb.py record --root . --receipt receipts/run.receipt.json \
  --no-kb-required --reason no-new-knowledge --delivery-out receipts/delivery.json

# 回查：用同一组维度确认新条目出现在默认前 20 条
python3 tools/kb.py query-back --root . --delivery receipts/delivery.json --top 20 --json
```

`query-back` 通过退出 0 并把 `kb_query_back_status` 写成 `pass`；有 id 查不到则退出 1 并写 `fail`。
`record` 与 `query-back` 都不改 `registry/skills.json`，索引只由 `record` 成功后整文件重建。

## 11. 自检

```bash
python3 -m unittest discover -s tests -q
python3 tools/secret_scan.py .
```

新增或修改的契约文件必须过时间契约检查：时间字段只用北京时间 `YYYY-MM-DD HH:MM:SS`，
不出现 `T` 分隔符、`Z` 后缀、数字时区偏移与小数秒。
