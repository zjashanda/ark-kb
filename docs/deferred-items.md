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
- 建议下一步：按 `asset-tools` / `ark-archive` 的方式补 `tools/time_lint.py`（从 `skillhub-sync/tools` 复制，带 `--self-test`）；这两个仓已于 2026-11-11 完成（`985aab6` / `f1a9302`），本仓尚未做。

## D5 lstest 无全仓文件级门禁（分目录扫描替代）

- 现状：`lstest` 未提交 `tools/time_lint.py`。分目录借用 `venusahisiburner/tools/time_lint.py --root <dir>` 实测：`scripts` 24 文件 0 违规、`adapters` 7 文件 0 违规、`docs` 41 文件 0 违规（`docs/voice-validation/.../autobus-burn-ota-report.md` 里 `12:30-13:30` 曾被误判 utc-offset，已改写为「12:30 至 13:30」，commit `90024ef`）。
- 不修的理由：`tests/` 有 24 条设备原始日志/历史回归夹具（含小数秒与 ISO `T`，属合法保留形状），JSON 夹具无法加行内豁免，提交全仓 `--gate` 必败。
- 建议下一步：先把 `tests/` 基线写成白名单记录，再提交 `tools/time_lint.py` 与全仓门禁。

## D6 venusahisiburner 仍自行枚举串口，未走 device-io 接口

- 现状：`device-io/docs/interface.md:3` 要求 `venusahisiburner` 与 `lstest` 使用 device-io 入口而非自行枚举 COM/tty；实际 `venusahisiburner` 在 `scripts/core/phases.py:36-38` 调 `serial.tools.list_ports.comports()`，`scripts/core/bench.py:120-127,169-171,194-211` 直接 `serial.Serial(...)`，`scripts/core/profile.py:39,130-131` 校验 `COM\d+`；仓库内 grep 无 `device-io` 字样。
- 影响：设备枚举口径分叉，device-io 的角色映射/权限探测无法作用于烧录流程；不影响烧录功能本身。
- 最小修复预览：新增 `--device-snapshot <device-io ports --format json 输出>`，preflight 优先按快照选口，无快照回退 pyserial；需真机回归，故本次不做。
- 建议下一步：与 venusahisiburner 真机回归（NOAH-45 未完成的真机验证）一并落地。

## D7 ark-dispatch 仍会为 CSK6012 选 mideaSmoke（设计选择，非缺陷）

- 现状：`examples/csk6012-burn.json` 的 plan 选中 `mideaSmoke`×3，`venusahisiburner` 落在 `excluded`。`mideaSmoke` 为 `status: legacy`、`reuse: low`、`projects: [CSK6012-midea-smoke]`，靠「设备型号命中 + 设备专用优先」胜出。
- 判定：`legacy` 在设计上不禁用（`dispatch.py` 的 blocked 码只有 archived/platform/project/device），`supersedes` 仅影响排除理由文案；venusahisiburner 的取代关系只覆盖 `tcl-device-autoburn`/`burn_bundle`，不含 mideaSmoke。属预期行为。
- 建议下一步：若要把 CSK6012 收到 venusahisiburner，需在 `routing.json.supersedes` 增一条或在台账把 mideaSmoke 置 archived，属口径决策，交 owner。

## D8 ark-kb 索引缺 venusahisiburner 条目

- 现状：`python3 tools/kb.py query --skill venusahisiburner` 命中 0；`index/by-skill.json` 只有 7 个 skill 键（cskflashtest、lstest、lstts、melotts、omnipickup、skillkb、军器监丞·pvm1005），`entries/knowledge/*.jsonl` 里 grep 不到 `venusahisiburner`。
- 判定：检索功能正常（`--device tcl` 命中 3/118、`--capability burn` 命中 1/1），属知识覆盖度缺口。
- 建议下一步：把 venusahisiburner 的烧录口径（时间契约、profile、资产清单）作为知识条目补录，由知识库 owner 决定 `confidence` 与证据文件。
