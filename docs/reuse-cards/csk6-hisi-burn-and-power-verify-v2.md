# CSK6+HISI 复用验证执行卡 v2（NOAH-239 修订）

适用节点：win003、win005 各 1 次。**不做多轮压测、不自动重试、失败即停。**

修订摘要（相对 NOAH-227 v1）：新增 §0 拓扑门禁；§4 稳定性判定按拓扑分流；判定表增加 topology 与版本验收两行。
依据条目：`kb-method-c3adcba01df0`（拓扑门禁）、`kb-knowledge-84602a2f32dc`（13 s 周期复位=仅模组预期行为）、
`kb-method-cad7be93134e`（7 项独立判定）。

## 0. 前置（缺一即停）

1. 条目必须已 `active`：从 8091 查询并记录 `knowledge_snapshot`（`source_commit`、`indexed_commit`、`freshness`、`entries`、`degraded`）。
   - 查询维度：`capability=burn-and-power-verify`、`device=CSK6`、`project=cskflashtest / VenusA+WS63`。
   - 只有 `status=active` 且非 stale/superseded 的条目可驱动执行；`pending` 只作提示，不得据以烧录。
2. **拓扑门禁（开工第一条必录）**：在 EXECUTION_CHECK 与测试报告显式写下
   - `topology=module_only` 或 `topology=baseboard_present`；
   - `baseboard_absent=true/false`（未接电控/底板时必填 true）；
   - SPI 对端是否在位（电控板/底板是否应答）。
   - 记录规则：仅模组时 `topology=module_only` + `baseboard_absent=true`；这一条决定 §4 稳定性口径。
3. 记录本节点 `agent_id`、`run_id`、任务目录、`plan.md`、EXECUTION_CHECK。
4. busy/无设备 → `SKIPPED_NO_DEVICE` 或 `BLOCKED`，不得写 PASS。

## 1. 设备与端口（对应 kb-knowledge-99ced0adc4e3）

- 重新枚举 CH344 与 VCOM，生成 `port-map.json`（control / csk_log / csk_burn / hisi 四个口）。
- **禁止复用其它节点的 COM 映射**：win003 dev01 = control COM36 / csk_log COM35 / csk_burn COM34 / hisi COM32；win005 dev01 = control COM15 / csk COM36 / burn COM37 / hisi COM39。仅作对照，不直接套用。

## 2. 预检 profile（对应 kb-bug-cdb93160a496）

- dryrun 校验 profile 必填段（csk6.burn 的 `invocation`、`success_markers`）。
- 缺段时从 `chips/csk6/chip.json` 原样补齐到 `work/profiles/` 派生副本再跑，不改芯片层与历史任务目录。
- 校验 `expected_partitions` 与本包分区集合一致（本次包为 9 个分区，含 `ws63_all_nv.bin`；按 8 判会误报 NEEDS_REVIEW）。

## 3. 单次烧录（各 1 次）

- CSK6：复用 `Uart_Burn_Tool 1.0.5`，记录 WRITE SIZE / 设备 MD5 / 4 个成功标记 / exit code / 耗时。
  - PASS 判据：WRITE SIZE = 5,685,248 B、MD5 = `0xf6d6369435d52784efe1119ebd08f582`、4 标记齐全、exit 0、上电出现 `AP Boot Ready !!!` + `venus ap appliction(V4.1.8@Nov 11 2026 12:27:56)`。
- HISI：记录 optLog 全文（分区列表 + 「烧写结果」）、exit code。
  - 分区集合与 profile 不一致 → `NEEDS_REVIEW`，不得写 PASS；写入失败才是 `FAIL`。
- 版本比较：先去掉前导 `V` 再比，且同时打印设备原文与包名原文（对应 kb-bug-aaacbd2d3429）。
  - 归一化只消掉 `V` 前缀；`46.1.5` vs `46.1.8` 这类真实差异照实记 FAIL/NEEDS_REVIEW（对应 kb-knowledge-5b92a7b0c5d9）。

## 4. 上下电 + 启动观测

- `uut-switch1.off` → 3 s → `uut-switch1.on`，记录 `switch_idx1_set: 0/1` 回执。
- 上电后同时抓 CSK 日志口（115200）与 HISI（1500000）**实际字节数**；0 字节即启动 FAIL（对应 kb-knowledge-8ec3191c1698，拓扑不豁免）。
- 稳定性窗口 120 s：统计复位次数、复位间隔、`read sn fail` / `config and flash has no config` / `board excetion` 等异常行、FATAL/ASSERT/panic。
- **按拓扑分流判定**：
  - `topology=baseboard_present`：120 s 内持续复位（含约 13 s 周期复位）→ 稳定性 `FAIL`，转查供电 / SPI 对端 / 固件版本。
  - `topology=module_only`：出现 SPI `frame error head:0xFFFF` → `send timeout` → `spi_packet_send fail:-4` → `baseboard fota` / `board ota read` → `board excetion -1` → `reset_reason: reset` / `reset type:2` 的约 13 s 周期复位 → 记 `EXPECTED_TOPOLOGY_BEHAVIOR`（等价 `NOT_APPLICABLE`），**不进整机最差项，不拉低烧录验收**。
  - 仅在模组场景下仍要区分：复位形态与上述链路不符（有 panic/assert/fatal/watchdog timeout，或 CSK 侧异常）时不得套用预期行为，按实际证据判。

## 5. 资源监测

- 采样 ≥ 60 s：BurnTool / Uart_Burn_Tool / python 的 Working Set、句柄、线程；宿主可用内存；结束后残留进程与孤儿进程。
- 正常区间参考 kb-knowledge-158d1416a657；`FAIL_TOOL_MEMORY_LEAK` 先看 `release_ok` 与残留进程再判（对应 kb-bug-a9e3072fbaa0）。
- 采样器没抓到工具进程 = `EVIDENCE_GAP`，写 NEEDS_REVIEW，不写 PASS。

## 6. 判定与回报（对应 kb-method-cad7be93134e / 7675c53f29b4）

逐项回报，整机结论取最差项：

| 项 | 结果 | 证据 |
|---|---|---|
| 知识快照（source/indexed/freshness/degraded） | | |
| **拓扑（module_only / baseboard_present，baseboard_absent）** | | |
| 设备与端口映射 | | |
| profile 预检 | | |
| CSK6 烧录 | | |
| HISI 烧录（分区集） | | |
| 上下电后启动（字节数） | | |
| 120 s 稳定性（仅 baseboard_present 判 FAIL） | | |
| **版本验收（设备原文 vs 包名原文）** | | |
| 资源监测 | | |

- 结论只能是 `PASS` / `FAIL` / `BLOCKED` / `NEEDS_REVIEW` / `SKIPPED_NO_DEVICE` / `EXPECTED_TOPOLOGY_BEHAVIOR`，`BLOCKED` 不得写成 `PASS`。
- 每条结论必须能追溯到条目 id + 本次原始证据路径；代码通过 ≠ 真机通过。
- 失败后**不复烧、不重试**，把需人工决策的下一步写进回执。
- 不写凭据；大文件只登记路径 + SHA-256，正文不进知识库。
