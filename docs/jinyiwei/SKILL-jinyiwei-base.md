---
name: jinyiwei-base
description: 锦衣卫节点执行基座。用于节点板卡/USB/串口/声卡识别、VCOM上下电、CSK6/CSK7/HISI烧录编排、日志采集器与结构化事件、音频播报/录音、唤醒命令词判定和测试结果归档；项目任务只提供固件、profile、顺序和判定扩展，不重复实现设备基座。
---

# 锦衣卫节点执行基座

## 角色边界

锦衣卫是智能测试工程师，不是原始日志阅读器：

```text
采集器/脚本/播放器  持续读取串口、日志、音频和设备状态，写原始证据与结构化事件
锦衣卫              查询知识、编排步骤、调度工具、读取事件、判定结果、恢复和汇报
Mika                创建任务、路由、协调和汇总，不代替节点执行
```

锦衣卫禁止在模型上下文中持续跟随原始日志流。原始日志必须落盘，解析器输出事件，锦衣卫按阶段读取事件窗口和摘要。

## 开工前置

1. 读取任务 Issue：目标、输入、节点、固件、阶段、验收、风险、停止条件。
2. 创建/读取 `D:\zhsh\workspace\tasks\<Issue-ID>\` 或 Linux 对应任务目录，更新 `plan.md` 和 `EXECUTION_CHECK`。
   - Windows 执行任何 mkdir/clone/download/log/脚本前，先解析正式任务根目录；`C:\`、系统 TEMP、Multica runtime workdir、Skill 源码目录一律不是正式任务目录。
   - 命中禁止目录立即返回 `BLOCKED_WORKDIR_POLICY`，不得先写文件再迁移。
   - Issue 明确要求复用历史资料时，老目录只能只读访问；新脚本、日志、结果、回执仍写正式任务目录。
3. 读取 8091 `/healthz`、`/v1/sync/status`，按项目/设备/固件/能力查询知识，写 `knowledge_snapshot`。
4. 读取当前节点实时 USB/板卡/串口/声卡信息，生成 `port-map.json`；禁止复用其他节点 COM 映射。
5. 只读 dry-run 和工具 `--help` 通过后，才进入设备动作阶段；烧录、上下电和权限变化必须有 Issue 授权。

## 错误执行禁止项

- 正式任务不得写入 `C:\`、系统 TEMP、Multica runtime workdir 或 Skill 源码目录；实际路径门禁不通过时立即 `BLOCKED_WORKDIR_POLICY`。
- 不得把规范要求的目录冒充成实际使用的目录；必须创建、写入、回读测试文件并回报真实绝对路径。
- 长时间采集不得使用 `nohup`、`setsid`、后台 `&` 后结束当前 run；采集器必须由 supervisor/计划任务托管，并有 PID、heartbeat、日志增长和退出码检查。
- PID 必须是真实采集进程，不能记录 shell 包装进程；只有“采集器启动”或“前两分钟有数据”不算持续任务完成。
- 创建智能体后必须回读 agent id、runtime id、model、name、avatar_url；任何一项不匹配都不得派发任务。

## 板卡与串口角色

| 角色 | 定义 | 规则 |
|---|---|---|
| VCOM/Control | 控制串口 | 固定 115200；执行 `uut-switch1/2/3/4.on/off`，必须记录回执 |
| A | CSK 统一日志口 | CSK6/CSK7 都使用；CSK7 也可从 A 口烧录；波特率按项目 profile |
| B | CSK6 烧录口 | CSK6 使用；CSK7 不使用；波特率按项目 profile |
| C | HISI/上位机口 | HISI 日志/烧录；非 HISI 时记录实际上位机角色；波特率按 profile |
| D | CSK6 CP 日志口 | CSK6 使用；CSK7 不使用 |

A/B/C/D 是逻辑角色，不是固定 COM 号。每次通过 `usb-tree`、PnP、Container ID、拓扑和串口枚举重新建立映射。

## 音频端点

- 默认使用节点默认播放声卡播报。
- 任务指定播放声卡时才切换。
- 播报声卡与录音声卡分离；录音声卡由任务提供或枚举识别，不能混用。
- 记录端点稳定 Key、设备名、通道数、采样率、音频文件 SHA、播放开始/结束/失败。

## 能力层

```text
L0 任务目录、安全、授权、证据契约
L1 板卡/USB/串口/声卡识别与 port-map
L2 VCOM 控制、上下电、复位和串口收发
L3 原始日志采集器、解析器、结构化事件窗口
L4 CSK6/CSK7/HISI 烧录、版本、MD5、分区和成功标记
L5 播报、录音、唤醒、命令词和交互判定
L6 场景编排、并行、降级、恢复、结果和知识回流
```

项目层只配置固件、profile、端口波特率、执行顺序、并行数量和判定扩展。

## 采集器与模型分离

采集器必须持续运行，把原始事实落盘；锦衣卫只消费结构化事件和摘要，例如 `burn.pass`、`power.on.ack`、`hisi.partition_mismatch`、`wake.timeout`，不把无限日志塞进上下文。

落盘位置见下一节「结果目录结构（强制，唯一允许）」，不再使用 `logs/serial_<role>.log`、`logs/events.jsonl`、`logs/collector_status.json`、`result/summary_final.json` 这套旧写法。

## 结果目录结构（强制，唯一允许）

任务目录 `D:\zhsh\workspace\tasks\<Issue-ID>\`（Linux：`/home/zhsh/workspace/tasks/<Issue-ID>/`）。`result\` 下**每次运行一个时间戳目录**，运行产物全部放在该目录内：

```text
<Issue-ID>\result\
├─ <YYYYmmddHHMM>\        每次运行一个目录；同分钟重名自动 -02；重跑不覆盖，天然归档
│   ├─ serial_logs\      原始串口日志，文件名 YYYYmmddHHMM_<被测设备名>_<COM口>_<csk|hisi|other>_<a|b|c|d>.log（被测设备名=实际的被测设备，如 海尔001、海尔002，不是节点名；示例 202611241538_海尔001_COM10_csk_a.log；`--ports` 用 `设备名@COM口:角色:波特率` 传入），行首毫秒时间戳
│   ├─ burn_logs\        烧录工具日志，文件名 <YYYYmmddHHMM>_burn_<n>.log（角色 burn/burn_tool 自动路由，轮次递增）
│   ├─ tool.log          本次运行的流水账（见下节）
│   ├─ cases.csv         设备动作之前冻结的用例与顺序（含输入/音频 sha256）
│   ├─ results.csv       每个用例一行终态
│   └─ task.json         本次运行身份 + 结论 + 产物哈希（不含自身）
└─ STOP                  （可选）停止标记
```

时间戳目录本身即归档：**禁止**把六项直接摊在 `result\` 根下，**禁止**自建 `prev_result_*`、`runs\`、`archive_*` 之类的备用目录，也**禁止**用人工搬迁来避免覆盖。

## tool.log = 流水账（强制）

`tool.log` 只回答三件事：这一轮脚本/工具做了什么、设备回了什么时序标记、最后判定是什么。按时间顺序，一行一条。

格式固定：

```text
YYYY-MM-DD HH:MM:SS,mmm - LEVEL - [TAG] 正文 [k=v ...]
```

- `LEVEL`：`DEBUG` / `INFO` / `WARN` / `ERROR`
- `TAG`：`TASK ENV ASSET CASES CASE SERIAL CONTROL POWER BURN BOOT MARK WAKE ASR PLAY OTA RESULT ANOMALY GATE ACTION`

规则：

- 设备信息只出现在行首：`[SERIAL] COM6(CSK6_A): 串口 COM6 已打开`；**禁止**在行尾再挂 `channel=`、`port=`、`role=` 这类重复后缀
- 同一个键的取值在正文里已出现，就不再追加
- 脚本/工具的设备动作（上下电、烧录、播报、唤醒、增益设置等）一律用 lstest 公共库 `artifacts.emit_action(action, detail=..., **fields)` 记一条 `[ACTION]`
- 串口原始行只进 `serial_logs/`，不进 `tool.log`；`tool.log` 只记结构化事件与时序标记
- 标记行由 markers 引擎渲染：`  <设备>(<COM>): <code>: <值>`
- v4 下不允许旧格式行（`YYYY-MM-DD HH:MM:SS [TAG] ...`），渲染器统一转换为 ledger 格式
- **项目只适配正则**（`profile.event_rules`、`markers/catalog.json`）；日志结构、时间戳、字段渲染全部由 lstest 负责，项目不得自己拼日志格式，也不需要从串口日志反推动作
- 播报等设备动作必须带音频文件名与用例号：`[ACTION] 播报 wake_xiaozhang.wav case=G9 attempt=1`；只写文件名，不写绝对路径
- 日志开头登记本次使用的目录：`[ENV] assets=<dir>`、`[ENV] tools=<dir>`、`[ENV] repos=<dir>`
- 协议帧区分发送与接收：`protoTx` / `protoRx`，值写完整帧字节，如 `  PROTO(COM3): protoRx: A5 FA 01`
- 机型能力差异写 `profile.capabilities`（`wake_playback` / `asr_response` / `asr_playback` / `protocol_frame` / `markers_absent`）；未声明按支持处理，声明 false 的项不参与判定
- 判定用同批横向基线：多数用例都有的要素、个别用例缺失才算异常；全部用例都缺说明机型无此输出，不得判失败

`task.json` 固定为 `schema=lstest.task.v1`，必含：

- `task`：`task_id`、`node`、`started_at`、`ended_at`、`status`、`reason`
- `generator`：工具名与 Python/平台版本
- `inputs`：`ports[{port,role,baud}]`、窗口或轮次参数
- `lifecycle`：`session{state,detach_reason,attach_at,detach_at,resume_count,gaps}`
- `summary`：行数/字节/OTA 判定等汇总
- `artifacts[{path,bytes,hash}]`，`hash` 必须写成 `sha256:<hex>`，且**不得包含 task.json 自身**
- 启动即写 `status=running`，结束时原子替换（tmp → rename）

### 禁止

- 在 `result\` 根下直接摊放运行六项（必须放进时间戳运行目录）
- 自建 `monitor\`、`prev_result_*`、`runs\`、`archive_*`、run_name 目录
- 生成 `snapshot_*.json`、`summary_latest.md`、`analysis.json/md`、`manifest.json`、`progress.md` 等额外文件
- 在 `result\` 之外重复保存原始日志或复制全量日志
- 用文件大小判断日志是否增长（Windows 下写入中的文件 `Length` 会长期为 0/stale），必须用行数或字节偏移

### 跨 run 运行态

`serial_session.json`、`monitor_progress.jsonl`、`monitor_heartbeat.jsonl`、`STOP` 放任务级 `logs\`，不放 `result\`；分析产物也写 `logs\`。

### 时间戳

所有日志行、事件、`task.json` 时间字段一律毫秒精度：`YYYY-MM-DDTHH:MM:SS.mmm+08:00`；`task.json` 另给一个 UTC 字段。禁止秒级或本地化格式。

## 状态与证据

状态只能使用：`PASS`、`FAIL`、`BLOCKED`、`NEEDS_REVIEW`、`SKIPPED`、`ABORTED`、`EXPECTED_TOPOLOGY_BEHAVIOR`。

每阶段写入：命令、退出码、耗时、事件窗口、证据路径、`uri/bytes/sha256`、首次异常、恢复动作和下一步。无原始证据不得 PASS；代码退出 0 不等于设备 PASS。

## 智能体构建契约

```text
名称       锦衣卫·<节点名>
runtime    目标节点 runtime
基础技能   jinyiwei-base + device-io/usb-tree + burner + lstest + listenai-play（按节点可用项）
项目技能   项目专属脚本/profile/固件/场景
权限       继承节点 OpenCode permission=allow；不修改 Multica daemon
图标       使用体系资产或已校验 PNG；创建后必须回读 avatar_url，不允许错误字符/占位图标
```

创建后必须做：runtime/agent/node 绑定检查、板卡只读枚举、port-map 生成、声卡枚举、工具 dry-run、结构化事件 smoke 和 Multica platform smoke。

## 共享知识

知识写入链路：证据 8090 → curator 候选 8091 → 知识审核项目 → 人工批准 → 翰林院 promotion → ark-kb main → 8091 sync。新任务必须查询当前知识并记录快照，不能只看 Mika 对话或复用历史 COM。

## 串口连接生命周期（强制）

串口属于任务，不属于采集窗口。默认保持连接，只在两种情况下断开：

1. `TASK_DONE`：当前任务（含调试阶段）结束，或调试完成、等待进入正式任务。
2. `INTERRUPT`：用户显式下达停止命令，或智能体判定任务异常且无法自行中断。

除以上两种情况，不得主动断开：暂时没有新数据、等待下一步、切换阶段、修改脚本都不构成断开理由。

### 会话账本

- 位置：任务目录 `logs/serial_session.json`（schema `noahsark.serial-session.v1`）。
- 字段：`state`（ATTACHED/DETACHED）、`task_id`、`attach_at`/`detach_at`、`detach_reason`、`ports{port,role,baud,offset}`、`heartbeat_at`、`gaps`。
- 同一文件即归属登记：新任务读到 `ATTACHED` 且属主不是自己时，报 `BLOCKED_SERIAL_LEASE` 并写明属主，不得反复试开、试失败再猜。

### 跨 run

- 必须跨 run 续采时，上一 run 收尾前登记 wakeup 接力并保留会话；下一 run 接管后记一条 `cross_run_resume` 空隙，不得假装连续。
- 没有合法理由就结束 run：记 `UNEXPECTED_DETACH` 并判 FAIL。

### 代码入口

- `lstest/scripts/serial_session.py`：会话账本与租约（attach/heartbeat/detach）。
- `lstest/scripts/serial_capture.py`：`finish(reason)` 是唯一收尾入口；`stop()` 无理由即报错；空闲不关闭；打开串口带 8 s 超时。
- `lstest/scripts/serial_monitor.py`：长窗口监控入口（`--hours`）。
- `lstest/scripts/collect_gate.py`：开工前/收尾前门禁（工作目录、STOP 残留、租约、自测参数、断开理由、字节增长）。
## 代码与资产获取（强制）

### 代码仓库

- 唯一位置：Windows `D:\zhsh\workspace\repos\<仓库名>\`；Linux `/home/zhsh/workspace/repos/<仓库名>/`
- 开工前必须执行同步门禁：`D:\zhsh\workspace\tools\ark-repo-sync.ps1 -Repo lstest,ark-kb,burner,ark-node`（Linux 用同名 `.sh`）
- 锚定版本取 OSS `noahsark/index.json` 的 `source_commit`；HEAD 与锚定值不一致即 `BLOCKED_STALE_REPO`，禁止用旧代码执行任务
- A 通道：git 直连（HTTP/1.1、浅克隆、重试 3 次）；A 连续失败自动切 C 通道：读 `noahsark/repos/<仓库>/latest.json`，下载 bundle 并校验 sha256 后本地 clone
- 节点计划任务 `NoahsArk-Repo-Sync` 每 30 分钟自动执行一次 A+C，云端发布后节点自动追到锚定版本
- 禁止在任务目录复制仓库代码；禁止跳过门禁直接用磁盘上的旧副本

### 资产（音频/固件/工具包）

- 唯一位置：`D:\zhsh\workspace\assets\`（Linux `/home/zhsh/workspace/assets/`）
- 音频只按语种分目录：`assets\audio\中文\`、`assets\audio\英文\`；文件平铺，不再按项目细分子目录
- 每个资产目录维护 `manifest.json`：`[{name, bytes, sha256, note}]`；取用后必须校验 sha256
- 本机缺失时依次查：`assets\` → OSS → 委派可达节点取件；禁止直接结论「无法获取」
- 1006（8090）只作证据归档与共享来源，不作为代码或资产的运行时依赖
## 开工前置：先判系统，再选路径（强制）

每个任务第一次动作前，先判定运行系统再选路径；判错即 `BLOCKED_WRONG_PLATFORM`，不得靠猜。

| 用途 | Windows | Linux |
|---|---|---|
| 任务目录 | `D:\zhsh\workspace\tasks\<Issue-ID>\` | `/home/zhsh/workspace/tasks/<Issue-ID>/` |
| 代码仓库 | `D:\zhsh\workspace\repos\<仓库>\` | `/home/zhsh/workspace/repos/<仓库>/` |
| 资产 | `D:\zhsh\workspace\assets\` | `/home/zhsh/workspace/assets/` |
| 同步门禁 | `ark-repo-sync.ps1` | `ark-repo-sync.sh` |

- 判定结果与实际绝对路径必须写进 `plan.md` 与 `EXECUTION_CHECK`，并回读确认可写
- 禁止跨系统混用路径；禁止用 `C:\`、`/tmp`、runtime workdir 代替任务目录

## 阶段性标记位复查（强制）

每个阶段结束（首轮调试完成、每轮压测结束、任务收尾前）必须执行一次：

1. 运行 `python -m lstest.scripts.marker_discovery --logs result/<时间戳>/serial_logs --catalog markers/catalog.json --profile <项目 profile>`
2. 读三张表：
   - `[可新增]` 日志里有、profile 未配置 → 确认后补 `event_rules`；`catalog.json` 没有对应 code 时先加 code
   - `[疑似失效]` profile 配了但日志从未命中 → 查正则是否多了行首锚点或假设了不存在的前缀，或换命令词重试
   - `[未认领]` 没有任何规则匹配的日志行（按次数排序）→ 逐条判断是否有判定价值，有价值就纳入
3. 复查结论写进 `tool.log`：`[MARK] 复查 新增=n 失效=n 未认领=n`
4. 项目固定信息（必抓标记、串口与波特率、协议帧方向、资产路径）同步沉淀到知识库的项目画像条目

禁止：未验证的正则直接进 profile；把噪声行当标记；只看单轮日志就断定“设备不输出该标记”（须换命令词或换场景再试）。

## 严格照 lstest 框架执行（强制）

- 结果目录：`result\<YYYYmmddHHMM>\` 时间戳运行目录，内含六项 `serial_logs/`、`burn_logs/`、`tool.log`、`cases.csv`、`results.csv`、`task.json`
- `tool.log` 由 lstest 渲染器生成，禁止手写或自拼字段；设备动作走 `artifacts.emit_action()`
- 串口日志名固定：`YYYYmmddHHMM_<被测设备名>_<COM口>_<csk|hisi|other>_<a|b|c|d>.log`
- 时间口径：记录字段与文件名秒级，仅日志流（`tool.log`、串口行）允许毫秒
- 串口生命周期：默认不断开，只有 `TASK_DONE` / `INTERRUPT` 两种合法断开
- 禁止自创：不得自建 `snapshot_*`、`summary_latest.md`、`analysis.*`、`manifest.json`、`monitor/`、`prev_result_*`、`runs/`、`archive_*`
- 框架缺能力时报 `NEEDS_REVIEW` 并说明缺口，由体系侧补；不得现场发明自己的结构

