# 能力边界：谁能"生成用例并跑真机"

> 用途：调度（`ark-dispatch`）要在多个同类 skill 里选一个。这份文档先把边界写清，不合并实现。
> 适用范围：`mars-moon`、`Trisolaris`、`Polaris` 三者，以及容易混用的 `arcs-aopu-test`、`tcl-test-sub`、`cskflashtest`。
> 更新日期：2026-11-07。所有结论来自仓库 README/SKILL.md 与目录结构，不含真机结论。

## 一句话定位

| skill | 一句话定位 | 输入 | 主要产物 | 适合 | 不适合 |
|---|---|---|---|---|---|
| `Polaris` | **通用真机 BDD 框架** | Cucumber feature + step/action registry + `polaris.local.json` | Event Runtime 事件断言结果 `PASS/FAIL/BLOCKED/TIMING_AMBIGUOUS` | 任何需要结构化用例、可复盘证据、断言口径统一的项目 | 一次性快速试跑（写 step/action 成本高）；不想维护本机配置的人 |
| `Trisolaris` | **项目沉淀** | 需求目录 + 项目 profile + 验证池 | 方案/用例/烧录/播放/串口断言 + 正式套件结果 | 已有资产的小度风扇、好太太晾衣机，以及要沿用其验证池的新项目 | 没有 profile 与需求目录的临时任务 |
| `mars-moon` | **bundle 化交付** | 需求文档、词表 Excel、`tone.h`、固件 | 可迁移 bundle（spec/cases/deviceInfo）+ dry-run/烧录/runner/归档 | 要把"项目 + 语料 + 固件 + 流程"打包交给现场或客户 | 单次调试、没有完整需求/词表/固件的场景 |

判定口诀：

- 要**换设备跑一套通用用例** → `Polaris`
- 要**复用已有项目资产与验证池** → `Trisolaris`
- 要**把整个项目打成可迁移包交付** → `mars-moon`

## 为什么不合并

1. 输入不同：Cucumber feature / 需求目录 / 需求文档+词表+固件，三者没有公共输入格式。
2. 断言模型不同：Event Runtime 事件断言 / 项目内置断言 / runner + 归档，合并会改变判定语义。
3. 产物与历史不可比：已有结果目录结构各自固定，合并后旧结果无法复算。
4. 依赖不同：`Polaris` 依赖本机 `polaris.local.json`；`Trisolaris` 依赖验证池；`mars-moon` 依赖 bundle 内容。

结论：**先划边界，不合并**。真要收敛，应先抽公共"事件/证据/结果"契约，而不是把文件搬到一个仓库。

## 同源与档案关系

| 关系 | 事实 | 处置 |
|---|---|---|
| `Polaris` ← `polaris-device-validation` | 后者 2026-06 后停更，`status=archived`、`replaced_by=Polaris` | 后者已加归档横幅，不要安装 |
| 两者曾有同一个 frontmatter `name` | 旧版都叫 `polaris-device-validation`，会装到同一目录互相覆盖 | `Polaris` 已改为 `name: Polaris`（2026-11-07） |
| `Trisolaris/tools/audio/listenai-play` | 是 `listenai-play` 的整份副本 | 本次只记录；升级时需同步或改外部依赖 |

## 容易混用的项目型 skill

这两类 skill 自带语料与压测编排，**不能拿去跑别的项目**：

| skill | 适用设备 | 串口 | 语料 | 替代关系 |
|---|---|---|---|---|
| `tcl-test-sub` | TCL 双麦空调 | CSK AP `COM20@921600`、上位机 `COM22@921600` | 2778 条 MP3 + 489 条核心命令 | 奥普用 `arcs-aopu-test`；通用 BDD 用 `Polaris` |
| `arcs-aopu-test` | 奥普/ARCS 离线语音 | 日志 `COM26@921600`、协议/门限 `COM28@9600` | 308 条 MP3 + 308 条词表 | TCL 用 `tcl-test-sub`；通用 BDD 用 `Polaris` |

补充：

- 烧录不在这三者里：CSK 烧录用 `cskflashtest`，CSK6012 单点用 `mideaSmoke`。
- 语音合成不在这三者里：统一用 `lstts`（`lstest` 已委托 `lstts_core`）。
- 三者都依赖本机串口/声卡，**代码测试通过 ≠ 真机验证通过**。

## 调度建议（给 ark-dispatch 的规则）

1. 任务里出现"交付包 / 词表 / tone.h / 迁移到现场" → 优先 `mars-moon`。
2. 任务里出现具体项目名且命中 `Trisolaris` 的既有项目（小度风扇、晾衣机） → `Trisolaris`。
3. 任务要求"可审计用例 + 事件断言 + 多设备复用" → `Polaris`。
4. 任务只要求"跑一轮唤醒/命令词看结果" → 项目型 skill（`tcl-test-sub` / `arcs-aopu-test`），而不是 `Polaris`。
5. 三者都不满足时输出 `confidence: low` 并要求人确认，不要硬选。
