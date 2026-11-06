# skill-kb v1 验收记录

日期：2026-11-06
范围：`zjashanda/ark-kb` 的 `schema/`、`tools/`、`entries/`、`index/`、`tests/`
不包含：任何真机验证结论（本 issue 只交付工具链）

## 验收矩阵

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 1 条真实回执跑通 record → query 命中 | 通过 | `docs/receipts/20261106-kb-selftest/run.receipt.json`（哈希校验通过）→ 4 条条目 → `query --device agent-linux` 命中 |
| 2 | 5 条以上不同设备/能力查询，结果合理 | 通过 | 下方查询表（8 条查询，设备 / 项目 / 能力 / skill 四类条件） |
| 3 | `kb.py lint` 对故意构造的坏条目报错 | 通过 | 下方 lint 演示：7 个错误、退出码 3 |
| 4 | 单测全绿，不访问网络 | 通过 | 21 条用例 `OK`；`sync` 用例使用本地 bare 仓库 |
| 5 | 推送前给审批包 | 待审 | 分支与 diff 见 issue 评论，未推送 |

## 1. 真实回执链路

回执来自本 issue 的实际自检执行，不是手写样例：

- `run_id`: `run-20261106-kb-v1-selftest`
- `result`: `pass`；`totals`: 21 条单测、0 失败
- `evidence_dir`: `evidence`（相对回执所在目录）
- 证据文件与哈希：`evidence/unittest.log`、`evidence/env.txt`（条目库 lint 在 record 之后单独执行，避免回执哈希与条目哈希互相等待）

`record` 时按 `evidence_sha256` 在本机逐个比对文件，全部命中才入库：

```
回执 run-20261106-kb-v1-selftest：新增 4 条，合并 0 条，supersede 0 条
  + [run] kb-run-42681662dc2c 执行记录：ark-kb v1 工具链自检（单测 21 条）
  + [method] kb-method-0205df2c95f8 回执证据必须校验哈希，不接受“路径像证据”
  + [method] kb-method-9b11d61e6bed 凭据扫描器缺失时失败关闭
  + [knowledge] kb-knowledge-60d65219fd43 query 命中计数会写盘
  ! skill skill-kb 未在台账登记，条目仍以 pending 入库
```

跨设备/跨项目查询命中（`--device agent-linux`，9 条命中取前 5）：

```
[pending] kb-knowledge-60d65219fd43  score=6  device=agent-linux · project=ark-kb
  query 命中计数会写盘
  kb.py query 默认给命中条目 hits += 1 并回写 entries；…
  - file:docs/receipts/20261106-kb-selftest/evidence/unittest.log sha256=… 已校验
```

命中计数验证：`query --device TCL-DUT --top 1` 后，`kb-knowledge-1cbdc4c52cf2` 的 `hits` 从 0 变为 1（已落盘）。

## 2. 查询验收

能力台账已在 `main`（`725d3f4`），查询与 lint 直接用默认路径 `registry/skills.json`，不再需要 `--registry`。下表是在 rebase 到 `725d3f4` 之后复跑的。

| 查询 | 命中/候选 | 前两条结果 | 人工判断 |
|---|---|---|---|
| `--device win009` | 5/6 | win009 台架的执行通道约束；melotts 提交了 .venv | 首条正确；通用条目按低分排在后面 |
| `--device TCL-DUT` | 5/6 | TCL 被测设备的硬件构成；melotts 提交了 .venv | 首条正确 |
| `--project TCL` | 5/7 | TCL 被测设备的硬件构成；win009 台架的执行通道约束 | 三条 TCL 相关条目全部命中 |
| `--capability 烧录` | 1/1 | cskflashtest 内嵌 lstest/scripts 副本 | 精确命中，无噪声 |
| `--capability 语音合成` | 2/2 | 运行时语音合成统一走 lstts；melotts 提交了 .venv | 两条都与合成仓库相关，首条是规范 |
| `--skill lstts` | 1/1 | 运行时语音合成统一走 lstts | 精确命中 |
| `--skill cskflashtest` | 1/1 | cskflashtest 内嵌 lstest/scripts 副本 | 精确命中 |
| `--device agent-linux` | 5/9 | query 命中计数会写盘；回执证据必须校验哈希 | 自检条目全部命中 |

噪声控制：`--skill` 查询会排除无 skill 归属的条目；设备查询保留“通用”条目但只给 1 分，排在设备专属条目之后。

## 3. lint 坏条目演示

把知识库复制到临时目录，构造 5 条坏条目（scope 写成字符串、重复 id、悬空的 `superseded_by`、条目里带模拟凭据、多出未定义字段），再跑 lint：

```
lint：16 条条目，7 个错误，12 个警告
  [error] entry kb-knowledge-111111111111: $.scope: 类型应为 object，实际 str
  [error] entry kb-knowledge-222222222222: superseded_by 指向不存在的条目 kb-knowledge-ffffffffffff
  [error] entry kb-knowledge-444444444444: $: 出现未定义字段 foo
  [error] 重复条目 id：kb-knowledge-0e8f85cddf7a（2 次）
  [error] index by-device: 键内容漂移 ['win009']
  [error] index by-capability: 键内容漂移 ['tcl', '台架', '执行通道', 'ssh']
  [error] 凭据规则命中 …/entries/knowledge/entries.jsonl（第 4 条）
exit=3
```

（复制条目时没有复制 `docs/`，所以还出现了“证据文件不在本机”的告警——这正是设计行为：证据目录不可达时降级为路径 + 哈希登记，不伪造校验结果。）

正常状态下（11 条条目）：

```
lint：11 条条目，0 个错误，4 个警告
  [warn] entry …: source_skill skill-kb 未在台账登记   # 自检条目，台账里确实没有 skill-kb
```

## 4. 单测

```
$ python3 -m unittest discover -s tests -v
Ran 21 tests in 0.22s
OK
```

覆盖范围：

- record：建条目与索引、幂等、缺证据拒绝、哈希不符拒绝、凭据拒绝、扫描器缺失失败关闭、两次独立验证升级、supersede 保留旧条目
- query：设备命中与 hits 落盘、能力走台账、stale 默认隐藏、返回摘要不返回全文
- lint：坏条目、索引漂移、凭据、未登记 skill（警告 / `--strict` 报错）
- sync：拒绝推 main、功能分支可推、能拉取上游
- schema：生成条目符合 `entry.v1`、回执缺字段能被 schema 拦住

全部用例不访问网络；`sync` 用本地 bare 仓库。

## 5. 已知限制与后续

- **台账已合入**：`registry/skills.json` 在 `main`（`725d3f4`），lint 直接校验 skill 名；只有 `skill-kb` 未登记（4 条告警）。
- **`skill-kb` 未登记**：自检条目的 `source_skill` 会持续告警，`--strict` 下会失败。建议在台账 v1.1 里补登记，而不是为了消警告伪造台账。
- **只验证工具链**：本回执的 `result=pass` 只说明工具与测试通过，不代表任何真机能力。
- **写入模型**：条目与索引整文件重写，多人并发写要先 `sync`；没有锁。
- **过期治理是半自动**：lint 提示“90 天零命中”，标 `stale` 仍需人/agent 执行。
- **索引不含台账派生词**：`--capability` 查询时现场用台账扩展关键词，索引只依赖条目自身，避免两笔 PR 合并顺序造成漂移。
