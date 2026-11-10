# 回执导入报告（2026-11-10）

本报告记录 9 份回执导入 ark-kb 的结果、验证证据与遗留问题。

## 输入

| 回执 | 质量 | 结论 | 来源 |
|---|---|---|---|
| `run-20261102-181057-tcl003-5rounds-5r` | formal | pass | 本机 tcl003 五轮冒烟 |
| `run-20261103-192523-tcl003-5rounds-5r` | formal | pass | 本机 tcl003 五轮冒烟（含完整性清单） |
| `run-20261104-112028-tcl003-10cmd-10r` | formal | fail | 本机 tcl003 十命令（11:20 场） |
| `run-20261104-113223-tcl003-10cmd-10r` | formal | fail | 本机 tcl003 十命令（11:32 场） |
| `run-20261104-142316-tcl003-edge-tts-10cmd-10r` | formal | pass | 本机 tcl003 edge-tts 十命令 |
| `run-20261104-144020-tcl003-indextts-10cmd-10r` | formal | fail | 本机 tcl003 indextts 十命令（第 3 轮固件崩溃） |
| `run-20261104-150954-tcl003-lstts-10cmd-10r` | formal | pass | 本机 tcl003 lstts 十命令 |
| `run-20261022-103329-win009-v15-u1-command` | candidate | needs_review | win009 远程扫描行 |
| `run-20261014-163403-win009-wake-interval` | candidate | blocked | win009 远程扫描行（结论与判定行冲突） |

正式回执 7 份，候选回执 2 份。tcl003 回执的证据副本在各自 `evidence/` 目录，哈希在转换时复算并写入 `evidence_sha256`。

证据副本做了两处脱敏，均记在回执的 `backfill.notes` 里：

- `task_config.json` 不归档（含设备编号与绝对路径），只把端口、轮次、随机种子、时间口径写进回执；
- `tool_logs/compat_launch.json`、`tool_logs/runtime_profile.json` 副本里的 `*_device_key` 替换为占位符。因此这两个副本的哈希与运行目录 `SHA256SUMS` 记录的原始哈希不再一致——`SHA256SUMS` 本身仍然归档，可核查原始值。

## 导入结果

正式回执按时间顺序导入，候选回执显式加 `--allow-candidate` 导入。

| 回执 | 新增条目 | 合并 |
|---|---|---|
| 20261102-181057 | run + method | 0 |
| 20261103-192523 | run + method | 0 |
| 20261104-112028 | run + knowledge | 0 |
| 20261104-113223 | run + knowledge | 0 |
| 20261104-142316 | run + method | 0 |
| 20261104-144020 | run + knowledge + bug | 0 |
| 20261104-150954 | run + method | 0 |
| 20261022-103329（候选） | run + method | 0 |
| 20261014-163403（候选） | run + method | 0 |

合计 19 条新条目，合并 0 条。条目清单：

| 类型 | 条目 |
|---|---|
| run | `kb-run-b1d69652f3be` 五轮冒烟（18:11 场） |
| run | `kb-run-89fb612bab53` 五轮冒烟（19:25 场） |
| run | `kb-run-1371072607ce` 十命令（11:20 场） |
| run | `kb-run-ee12d5eb9ea7` 十命令（11:32 场） |
| run | `kb-run-230623b02f26` edge-tts 十命令 |
| run | `kb-run-16a9cc2b6ccd` indextts 十命令（第 3 轮崩溃） |
| run | `kb-run-cc56dd024a22` lstts 十命令 |
| run | `kb-run-7fe400264b40` win009 v15 单命令（候选） |
| run | `kb-run-f5452cbfa17d` win009 唤醒间隔（候选） |
| knowledge | `kb-knowledge-597f2e028a57` ASR 超时占多数时不能据 network_down 归因网络 |
| knowledge | `kb-knowledge-7c79f1217c93` 同台架连续两场识别率波动不足以判定固件退化 |
| knowledge | `kb-knowledge-47f5e67ad298` indextts 调高温度后固件崩溃且后续轮次全失效 |
| method | `kb-method-dfdcf389e051` 归档阶段必须产出完整性清单 |
| method | `kb-method-e40eaaca8156` 五轮冒烟不能替代长稳结论 |
| method | `kb-method-e464b5e9a536` edge-tts 全通过可作为 indextts 故障的对照基线 |
| method | `kb-method-4506a0f71d3b` lstts 与 edge-tts 均全通过说明 TTS 场景不是崩溃诱因 |
| method | `kb-method-419905a1c3d3` 扫描推断的结论必须以日志判定行为准（候选） |
| method | `kb-method-2866383e2331` 远程扫描行只能生成候选回执（候选） |
| bug | `kb-bug-a6039e398e31` indextts 场景调高温度步骤触发 CSK 固件崩溃且未自愈 |

自检回执 `run-20261106-kb-v1-selftest` 已升级为完整 v1 字段（补 node / toolchain / steps / recovery / stop_conditions），原 run_id、计数、证据哈希与 lessons 均保留；再次导入时按幂等规则跳过。

## 去重与幂等

三处验证：

1. **回执级幂等**。自检回执二次导入输出「已入库，跳过（record 幂等）」，不产生新条目。
2. **条目级去重**。19 条全部为新条目，没有触发相似度合并。`scope_key`（device / project / firmware）在 7 份 tcl003 回执中完全相同，若按标题相似度合并，同一天多场运行会被压成一条——因此本任务修正了 `cmd_record`：**`type=run` 的条目不再走相似度合并**，只按 `run_id` 做幂等判断，其余类型（knowledge / method / bug）保持 0.86 阈值不变。对应单测 `RunEntryIdentityTests`。
3. **候选不合并**。候选回执的条目永不与正式条目合并，且带 `evidence-gap` 标签的条目永不被提升为 `active`（单测 `CandidateReceiptTests`）。

## lint

```
python3 tools/kb.py lint --allow-missing-scanner
lint：141 条条目，0 个错误，177 个警告
```

177 个警告里，173 个是既有的「证据文件不在本机（按路径 + 哈希登记）」——那些条目的证据留在 win009 等远端机器，属预期；4 个是本次候选条目的 `evidence-gap` 提示，属预期。

**过程中修复了一个既有缺陷**：`kb-knowledge-4871f3474f8c`（pvm1005 断电恢复命令口径）把 `status: active` 误写进了 `confidence` 字段，导致 lint 报 1 个错误。已改为 `confidence: medium`，`status` 保持 pending。该条目是上一个提交引入的，与本任务无关，但不修就无法给出干净的 lint 结果。

## 可检索性

三个视角各查一次全量结果（`--top 40 --no-hit-count`，输出存 `docs/receipts/20261110-receipt-backfill-verify/`），19 条新条目里 15 条命中，另外 4 条是被 `evidence-gap` 隔离的候选条目——它们只在直接检索时出现，不参与调度。

| 查询 | 命中总量 | 新条目命中 |
|---|---|---|
| `query --capability wake-recognition` | 28 条 | 15 条，含 run / knowledge / method / bug 四类 |
| `query --skill tcl-test-sub` | 19 条 | 15 条 |
| `query --device "TCL 智能语音设备（CSK7 + HI3863 双 MCU）"` | 134 条 | 15 条 |

索引侧核对：`index/by-capability.json` 的 `wakerecognition`、`串口` 键，`index/by-skill.json` 的 `tcltestsub` 键都已包含新条目。

一个使用上的坑要记下来：`query` 默认 `--top 5`，排序先看评分、再看状态（active 优先于 pending）、再看命中次数。新入库的条目是 pending 且命中次数为 0，默认视图里会被既有 active 条目挤下去，看起来像"没入库"。做可检索性验证必须显式给 `--top`，否则会误判。

## 下一次调度验证

请求 `docs/receipts/20261110-receipt-backfill-verify/request-tcl003-overnight.json`（tcl003 8 小时通宵，节点 bszT14，reset_allowed=true，端口 COM3/COM4/COM6），用新知识库生成计划：

```
python3 scripts/dispatch.py plan --request ... --out ... --kb ../ark-kb
python3 scripts/dispatch.py check --plan ...
check: OK p-20261110-f6de：9 步，全部 skill 在台账内且非 archived
```

生成结果（`plan-tcl003-overnight.json`）：

- **前置检查**：`plan.preconditions` 最后一条直接引用新条目 —— 「indextts 调高温度后固件崩溃且后续轮次全失效：……（kb:kb-knowledge-47f5e67ad298）」。该条目因带 `串口`、`台架` 标签被分类为 `precheck`，说明标签口径生效。
- **恢复动作**：`recovery.R1 algo-restart`，命令 `algo.restart 1` 写入 COM3@921600，`gate` 为 10 秒内端口重新产生字节，`after_fail` 含连续 3 次快速崩溃即停止，`verify` 要求再跑一轮冒烟。`basis: kb:kb-bug-241022256518`。
- **停止规则**：三条全部来自知识库，`crash-round-cluster` 引用 `kb:kb-knowledge-47f5e67ad298`（新），`crash-signature-budget` 引用 `kb:kb-knowledge-0f2bab9750fc`（既有），`recovery-ineffective` 引用 `kb:kb-bug-a6039e398e31`（新）。
- **候选隔离**：`kb-run-7fe400264b40`、`kb-method-2866383e2331` 等带 `evidence-gap` 的条目**没有出现在计划的 `kb` 列表里**。为此在 `dispatch.py` 的 `load_kb` 增加了候选过滤（带 `evidence-gap` 标签的条目与 stale / superseded 同等对待），并补了单测 `EvidenceGapIsolation`，回归 75 项全过。

## 失败项与遗留

| 项 | 状态 | 说明 |
|---|---|---|
| 凭据扫描 | 跳过 | 本机没有 skill-git 的 `scripts/skill_assets.py`，`record` 与 `lint` 均按 `--allow-missing-scanner` 降级。已用正则人工核对 9 份回执与证据副本，未发现内网地址、账号、口令、token；推送公开仓库前仍应在装有扫描器的机器上重跑一次 lint。 |
| NAS 两条任务 | 拒收 | 含内网地址、第三方账号与他人目录清单，脱敏后不足以复核；详见 `conversion-list.csv`。 |
| win010 两条回收站产物 | 拒收 | 计数自相矛盾 / 运行未结束。 |
| 9050 行扫描数据 | 0 转正式 | 原始产物未取回本机，只产出 2 份候选回执；详见 `scan-summary.md`。 |
| 144020 固件转储 | 缺失 | 崩溃现场未生成 dump，无法做栈级定位，已作为 bug 沉淀而非回执缺口。 |
