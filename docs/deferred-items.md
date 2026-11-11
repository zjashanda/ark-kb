# ark-kb 时间契约待办（NOAH-56 验收记录）

> 生成时间：2026-11-11。以下条目为本次验收实测发现的**未通过 / 需后续处理**项，不计入本次「时间契约收口」的通过范围。

## D1 存储层 schema 仍为 RFC3339（date-time）

- 现状：`schema/entry.v1.json:38-39`（`created` / `updated`）、`schema/index.v1.json:11`（`generated_at`）、`schema/receipt.v1.json:98,102`（`started_at` / `ended_at`）均声明 `"format": "date-time"`。
- 生成侧：`tools/kb.py:54 now_iso()` 产出 `...Z`；`tools/ark_receipt.py:70 to_rfc3339()` 把 manifest 的空格时间补成 `T` + 偏移。
- 影响：索引 `generated_at`、条目 `created`/`updated`、回执 `started_at`/`ended_at` 默认输出仍是 RFC3339，与 R1（`YYYY-MM-DD HH:MM:SS`）不一致。`python3 ../skillhub-sync/tools/time_lint.py --root .` 在本仓命中 33 条，其中本条占 19 条（含历史回执 12 条）。
- 不修的理由：这是持久化 schema 与跨仓消费契约（ark-dispatch 消费知识、回执被归档/仪表盘读取），改格式需 schema v2 + 数据迁移 + 下游确认，超出「最小修复」范围。
- 建议下一步：单独立项 `ark-kb schema v2：时间字段统一空格秒级`，含 entries/index/receipt 三个 schema 的版本升级、迁移脚本、下游联调。

## D2 条目 confidence 取值不合枚举

- 现状：`entries/knowledge/entries.jsonl` 第 36 行条目 `kb-knowledge-4871f3474f8c`（「pvm1005 TCL 断电恢复命令口径」）`confidence: "active"`，而 `schema/entry.v1.json` 枚举为 `high|medium|low`。
- 影响：`python3 tools/kb.py lint --allow-missing-scanner` → `123 条条目，1 个错误，188 个警告`，退出码 3；这是唯一 error。
- 不修的理由：该条目在 `eb6bb09` 之前已存在，改 `confidence` 等于替知识库 owner 篡改可信度等级；其 `created`/`updated` 也是历史 RFC3339，按「不迁移历史数据」原则保留。
- 建议下一步：由知识库 owner 定值后单独提交。

## D3 证据目录缺失导致的 188 个 warn

- 现状：`kb.py lint` 的 warn 主要是「证据文件不在本机 `../evidence/...`」。
- 原因：本次验收工作区只检出 11 个仓库，未检出 `evidence/` 归档目录，属预期环境差异。
- 建议下一步：在含 `evidence/` 的节点（linux003 归档区）复跑 lint 复核。

## D4 本仓无独立 time-lint 入口

- 现状：`ark-kb/tools/` 只有 `time_contract_check.py`（跨仓 oracle）与 secret scan，没有 `tools/time_lint.py`。
- 影响：本仓自有文件的格式门禁依赖 `../skillhub-sync/tools/time_lint.py --root .` 与本仓 `time_contract_check.py --only samples` 组合。
- 建议下一步：与 asset-tools / lstest 一起补 `tools/time_lint.py`（从 skillhub-sync 复制并加 `--self-test`）。
