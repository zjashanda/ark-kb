# 时间契约（全工作区）

> 状态：R1–R3 已生效；**R4（设备层毫秒精度）BLOCKED，待郑保山裁决**。
> 适用范围：Ark 工作区全部仓库与节点——已检出的 10 个仓库（`../`）与未检出仓库同样适用，节点侧脚本不例外。
> 最后核对：2026-11-11。表内每格都来自仓库实测；无法验证的写「待核」。

## 适用范围

- 所有仓库写出的用户可见时间、机器可读 JSON 字段、回执、日志、文档示例、schema。
- 所有节点与台架上的脚本，包括临时脚本与一次性压测脚本。
- 不约束外部系统自己的输出：外部原始值只能以 `raw_*` 字段原样保存（见 R3）。
- 本仓自身的持久化 schema（`schema/entry.v1.json`、`schema/index.v1.json`、`schema/receipt.v1.json`）声明 `format: date-time`：索引 `generated_at`、条目 `created`/`updated`、回执 `started_at`/`ended_at` 属存储层，按 schema v1 仍输出 RFC3339；取消该例外需要 schema v2 迁移并与下游（ark-dispatch 消费知识）联调，已列入待办，**不计入本次通过**（见 `docs/deferred-items.md`）。

## 规则

### R1 时间字段 = 北京时间 `YYYY-MM-DD HH:MM:SS`

所有时间字段一律写北京时间（Asia/Shanghai，UTC+8，无夏令时）的墙钟，秒精度，空格分隔。**禁止**出现 `T` 分隔符、`Z` 后缀、`+08:00` 类偏移、小数秒、以及字符串里的 `UTC` / `GMT` 字样。

来源：`ark-archive/docs/time-contract.md`（决策 NOAH-43）、`ark-archive/lib/ark_time.py` 的 `CONTRACT_FORMAT = "%Y-%m-%d %H:%M:%S"`、`ark-node/ark_node/util.py` 的 `FMT_DISPLAY` 文档字符串。

### R2 文件名/目录名时间戳 = `YYYYMMDD-HHMMSS`

8 位日期 + 连字符 + 6 位时间，**不带时区**。2026-11-11 起全工作区统一。

- `ark-archive` 在 2026-11-11 前用下划线 `YYYYMMDD_HHMMSS`。已存在的归档/暂存/隔离目录**只读兼容、不迁移不改名**（改名会破坏 manifest 路径与审计链）。
- 识别历史目录用 `is_legacy_stamp()`（正则 `^\d{8}_\d{6}$` 且校验真实日期）；需要换算时用 `python3 lib/ark_time.py legacy-stamp "20261110_120956"`，只做字符串换算，不碰磁盘。
- 新数据一律连字符：`to_stamp()` / `ark_stamp` / `Get-ArkTimeStamp` 只输出新格式。

### R3 外部原始时间只进 `raw_*`，RFC3339 只能显式开启

- 设备日志、`summary_final.json`、上游 API 返回的时间，只能放在以 `raw_` 开头的字段里，原样保留，不改写、不透传给用户可见字段。
- RFC3339 输出**仅**在 `--legacy-rfc3339` 这类显式开关下允许（`ark-archive` 的 `archived_at` 兼容旧消费者），**不得作为默认**。
- 解析层可以接受 RFC3339 输入（外部数据本来就长这样），但输出必须回到 R1 格式；解析处的字面量要带 `time-lint:allow` 或等价豁免标记。

### R4 设备层毫秒精度：已裁决为方案 A，已落地（2026-11-11）

**裁决**：记录层统一 `YYYY-MM-DD HH:MM:SS`（空格、秒级、无时区）；需要毫秒的原始时序只保留在 `raw_*` 字段或 step 内的设备侧字段，并在字段名与文档中标注为设备层。

**落地结果**：`venusahisiburner` 已改造完毕（commit `8bd7ddd`）：

- `scripts/core/contract.py`：`TIME_CONTRACT` / `_TIME_RE` / `_TIME_FMT` / `now_bj()` / `parse_bj()` 全部改为空格秒级；`is_bj_timestamp()` 反向收紧，`T`、小数秒、`Z`、`+08:00` 一律拒绝。
- `references/result-contract.md`：时间段重写，新增 `raw_*` 规则；`assets/manifest.json` 的 `updated_at` 改新格式。
- 新增 `tools/time_lint.py`（12 类违规形状，`--gate` / `--self-test`），与其他 5 个仓库的本地闸门对齐；设备原始日志夹具用 `time-lint:allow` 逐行标注。
- 证据：50 tests OK；`lint_scan.py --strict` PASS；`tools/time_lint.py --gate` 0 违规 / 22 文件；本仓库 `time_contract_check.py --only samples` 6/6 PASS。

**方案 B（全线带 `T` + 毫秒）未采用**，记录在此仅作历史背景。

## 各仓库实现位置（2026-11-11 实测）

| 仓库 | 实现文件 | 时间字段格式 | 文件名戳格式 | lint 入口 | 实测结果 |
|---|---|---|---|---|---|
| `ark-archive` | `lib/ark_time.py`（`CONTRACT_FORMAT` / `STAMP_FORMAT`；`ark-time.sh`、`ark-time.ps1` 为薄封装） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS`；历史 `YYYYMMDD_HHMMSS` 只读兼容 | `python3 lib/ark_time.py audit "<value>"`（退出 1 = 违规） | `2026-11-10 12:09:56` → ok；`2026-11-10T12:09:56` → 违规（含 ISO `T`） | <!-- time-lint:allow -->
| `ark-node` | `ark_node/util.py`（`FMT_DISPLAY` / `FMT_STAMP`） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS` | `python3 tools/time_lint.py` | 0 violation / 35 files |
| `asset-tools` | `asset_tools/util.py`（`FMT_DISPLAY` / `FMT_STAMP`；另有 `format_rfc3339` 供 `status.py` 的 `generated_at_rfc3339` 兼容字段） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS`（`cache.py` 使用） | 无独立 time-lint（`tools/` 只有 secret scan）— **待补** | — （待补 lint 后回填） |
| `tts-runtime` | `tts_runtime/util.py`（`FMT_DISPLAY` / `FMT_STAMP`） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS` | `python3 tools/time_lint.py` | 0 违规 |
| `audio-runtime` | `audio_runtime/models.py`（`TIMESTAMP_FORMAT`）、`audio_runtime/record.py`（录音文件戳） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS` | `python3 tools/time_lint.py` | 0 violation / 0 raw_* exemption |
| `device-io` | `device_io/schema.py`（`_TIME_FMT`，`now_bj()`） | `YYYY-MM-DD HH:MM:SS` | 不生成（本仓库无目录戳） | `python3 tools/time_lint.py` | 0 violations / 41 files |
| `skillhub-sync` | `skill_sync.py`（`FMT_TIME` / `FMT_STAMP`） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS` | `python3 tools/time_lint.py` | PASS：0 violation / 18 files，17 处 allow（含 3 条正样例） |
| `venusahisiburner` | `scripts/core/contract.py`（`TIME_CONTRACT`、`_TIME_FMT`） | `YYYY-MM-DD HH:MM:SS` | 不生成（`--run-dir` 由调用方给定） | `python3 tools/time_lint.py --gate`；另有 `scripts/lint_scan.py --strict`（schema/资产/凭据/编译） | 0 违规 / 22 文件，25 处 allow；契约自带 `is_bj_timestamp()` |
| `lstest` | `scripts/core.py`（`FMT_TEXT` / `FMT_STAMP` / `now_text()`；`scripts/audio_synthesis.py` 同名 `now_iso()` 已改） | `YYYY-MM-DD HH:MM:SS` | `YYYYMMDD-HHMMSS`（`TaskArtifacts` 运行目录） | 无独立 time-lint（待补） | 193 tests OK；`tool.log` 行首时间戳输出为秒级，校验器兼容历史毫秒行 |

## 交叉验证

目标是让**每个仓库的 lint 跑在其它仓库的样例上**，而不是只检查自己：把 A 仓库产出的时间字符串喂给 B 仓库的校验函数，期望全矩阵 PASS。任一仓库的 lint 过宽（放过 `T`/`Z`/毫秒）或过窄（拒绝合法空格格式）都会在矩阵里暴露。

入口（脚本由 `tools/` 任务提供，本文件只描述用法，不改它）：

```bash
python3 tools/time_contract_check.py --repos ../ --json
python3 tools/time_contract_check.py --repos ../ --only samples
```

- 样例一致性：同一组样例喂给各仓库的 lint / 契约校验函数，比较判定是否一致。
- 跨仓库矩阵：用 A 仓库的 lint 扫描 B 仓库的源码树，检查「A 的 lint 判 B 的产物违规」这类冲突。
- 不再有任何「待裁决例外」开关：`--allow-pending-legacy` 已于 2026-11-11 随 R4 落地一并移除，任何仓库判定不一致都直接记 `FAIL`。
- `raw_*` 豁免不算通过，只算「原样保留」，输出里单独计列。

### 结论（2026-11-11 收口实测）

`python3 tools/time_contract_check.py --repos ../ --only samples` 退出码 0，6 个可判定仓库对同一组样例判定完全一致：

| 仓库 | 6 条样例判定 | 自测 |
|---|---|---|
| `ark-archive` | PASS | `python3 lib/ark_time.py check` 与 `audit` 一致；47 tests OK |
| `ark-node` | PASS | 0 violation / 35 files；58 tests OK（skipped=1） |
| `device-io` | PASS | 0 violations |
| `tts-runtime` | PASS | 0 违规 |
| `skillhub-sync` | PASS | 0 violation / 18 files，17 处 allow；18 条自检样例；28 tests OK |
| `audio-runtime` | 仅自身仓库扫描（不接受外部目标） | `tools/time_lint.py` 四类值规则齐全，0 violation |
| `asset-tools` | 无 lint，无法判定 | lint **待补** |
| `lstest` | 无 lint，无法判定 | `scripts/core.py` 三个时间函数统一为 `now_text()`；193 tests OK |
| `venusahisiburner` | PASS | 契约已改空格秒级（commit `8bd7ddd`）；50 tests OK；`tools/time_lint.py --gate` 0 违规 |

收敛过程（本轮实际改动）：`skillhub-sync` 的 UTC/`Z` 违约被修（`now_utc()`/`stamp_compact()` → `now_text()`/`now_stamp()`，全部北京时间无后缀）；`ark-node` 与 `skillhub-sync` 补上缺失的「小数秒」值规则，`skillhub-sync` 另补 `Z` 后缀与时区偏移两条；`lstest` 修掉 `now_iso()` 的 `isoformat(milliseconds)`、`now_human()` 的空格毫秒与运行目录下划线戳。

矩阵（A 仓库 lint 扫 B 仓库源码）**只作信息展示，不参与 PASS/FAIL**：它必然命中别的仓库文档里作为反例引用的 `T`/`Z` 字样，以及 `time-lint:allow` 写法差异；把这些当冲突会产生假阳性。真正的验收口径是「同一组样例在各仓库判定一致」，即上表。

`venusahisiburner` 已于 2026-11-11 按 R4 方案 A 落地（commit `8bd7ddd`），6 个可判定仓库样例判定完全一致。

## 违规样例（正反例）

| 场景 | 判定 | 样例 |
|---|---|---|
| 记录层时间字段 | PASS | `2026-11-10 12:09:56` |
| 文件名/目录名戳 | PASS | `20261110-120956` |
| ISO `T` 分隔 | FAIL | `2026-11-10T12:09:56` | <!-- time-lint:allow -->
| `Z` 后缀 | FAIL | `2026-11-10 12:09:56Z` | <!-- time-lint:allow -->
| 时区偏移 | FAIL | `2026-11-10 12:09:56+08:00` | <!-- time-lint:allow -->
| 下划线戳（新数据） | FAIL | `20261110_120956`（仅历史目录读取时兼容） |
| 毫秒（记录层） | FAIL（R4 已裁决：记录层禁小数秒，只进 `raw_*`） | `2026-11-10 12:09:56.123` | <!-- time-lint:allow -->
| 外部原始值 | PASS（仅当字段名 `raw_*`） | `raw_started_at: "2026-11-09T02:54:39Z"` | <!-- time-lint:allow -->

> 「FAIL」列里的写法只用于说明违规形态；任何脚本输出、schema 示例、文档正文都不得把它们当作格式示范（出现时须带 lint 豁免标记）。

## 待补（不阻塞本次收口）

- `asset-tools`：复用 `ark-node/tools/time_lint.py` 的规则集补一个同名入口，纳入 `docs`/JSON/`py` 三类扫描。
- `lstest`：同样补 `tools/time_lint.py`；补完后再加入 `tools/time_contract_check.py` 的 `LINTS` 适配器与 `--targets`。

两处缺口的前提相同：先把规则文件本身带上 `time-lint:allow` 标注，否则 lint 会命中自己的反例字符串。
