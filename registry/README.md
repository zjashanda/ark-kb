# 能力台账 v1

NoahsArk 工作区 46 个仓库的能力、适用设备/项目与可用状态的单一事实源。机器可读版在同目录 [`skills.json`](skills.json)。

本版只做清点，不改任何被调查仓库；所有描述来自仓库 README、`SKILL.md`、顶层目录与最近提交，不包含代码、配置或凭据内容。

相关文档：

- [`docs/capability-boundaries.md`](../docs/capability-boundaries.md)：`Polaris` / `Trisolaris` / `mars-moon` 的选型边界（不合并的理由）。
- [`docs/high-reuse-usage.md`](../docs/high-reuse-usage.md)：`reuse: high` 的「谁在用、怎么调用」及证据强度。
- [`docs/time-contract.md`](../docs/time-contract.md)：全工作区时间字段与文件名戳契约；设备层毫秒精度待裁决。
- [`docs/archive-candidates.md`](../docs/archive-candidates.md)：4 个归档候选的冻结提案（未批准不执行）。
- [`docs/entrances-final.md`](../docs/entrances-final.md)：各仓库统一入口与命令清单。

## 数据来源与范围

- 采集：GitHub API 只读（`zjashanda`，46 个仓库；2026-11-06 首采 35 个，其中 4 个私有）。2026-11-11 补录 7 个 canonical 仓库与 4 个旧入口/跨仓库契约条目（NOAH-55）。
- 逐仓库核对：README、`SKILL.md` 全文、顶层文件清单、最近提交、`requirements.txt` 与关键 payload 目录。
- 私有仓库（`zhsh`、`fileball`、`qw-email-handle`、`a4m-Jenkins`）只能读到 README，依赖标注为“待核验”，不臆造。`tcl-device-autoburn` 是空/私有仓库，GitHub 不可读，只能依据节点侧说明记录。
- `last_verified` = 本台账静态核验日期（元数据 + 文档 + 依赖清单），**不等于真机验证**。真机结论只能来自节点侧执行证据。

## 字段与口径

| 字段 | 取值 | 说明 |
|---|---|---|
| `layer` | `spec` / `kernel` / `capability` / `knowledge` / `orchestration` / `tool` | 五层架构 + 工具支撑；`knowledge` 层含 `ark-kb`（台账/条目/索引的唯一事实源） |
| `status` | `active` / `legacy` / `archived` | 见下 |
| `reuse` | `high` / `medium` / `low` | 被 ≥2 个 skill 引用或有跨项目独立价值 = high；单一项目群内可复用 = medium；写死型号/协议/硬件 = low |
| `platform` | `windows` / `linux` | 文档里声明或入口脚本实际支持的平台 |
| `entry` | 相对路径 | 主入口；纯文档类 skill 记为 `SKILL.md`，目录型 payload 记为目录/批处理入口 |
| 空集合 | `["无"]` | 为满足“无空字段”，无依赖/无硬件统一写 `["无"]`，便于 grep 与校验 |

**状态判定**（可复核，最近推送日期已列在对照表里）：

- `active`：仍在用或被其他 skill/平台引用，最近 6 个月有更新；纯工具类（`beep-locator`、`melotts`）即使不常更新，只要能力仍可直接使用也记 active。
- `legacy`：项目已收尾、绑定单一项目，但资产与方法论仍可复用；新任务不应默认选它。
- `archived`：已被替代或与方舟无关，只作历史参照。

当前分布（由 `skills.json` 程序统计，2026-11-11）：`active` 32 / `legacy` 10 / `archived` 4；分层 `spec` 4 / `kernel` 7 / `capability` 17 / `knowledge` 1 / `tool` 14 / `orchestration` 3；复用 `high` 27 / `medium` 11 / `low` 8。复算命令见文末[校验](#校验)。

## 对照表

### 规范层（spec）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `skill-creator` | 创建/更新 Codex skill 的规范与模板：目录结构、SKILL.md 写法、命名规则，以及交付前必须通过的“禁止弹窗”终端审查项。 | 通用 | — | Win/Linux | high | active | 2026-11-04 |  |
| `skill-git` | Skill 发布门禁工具：建/校验 GitHub 同名仓库、扫描凭据、dry-run 预览、diff 比对、pull 回拉与 OSS 资产归档。 | 通用 | — | Win/Linux | high | active | 2026-11-06 |  |
| `test-plan-architect` | 把设备测试需求编译成可执行的 aitest.profilepack.v1（profile、fixture、case contract、oracle），并做预检与 B 类取证清单。 | 通用 | — | Win/Linux | high | active | 2026-10-08 |  |
| `trails` | 日常脚本与测试工具的统一工程规范：单入口、结果目录、task.log、CSV/JSON、原始证据、状态判定、停止恢复与交付格式。 | 通用 | — | Win/Linux | high | active | 2026-08-10 |  |

### 内核层（kernel）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `asset-tools` | 资产供给层：发现/manifest/校验/内容寻址缓存/供给，供烧录与测试取资产。 | 通用 | — | Win/Linux | high | active | 2026-11-10 | 默认 dry-run；不归档、不烧录、不跑测试 |
| `audio-runtime` | 音频视图与执行层：端点枚举、媒体探测、单/双设备播放、Windows 多 Host API 原始 PCM 录音、转码标准化。 | 通用 | 播报声卡、录音声卡、USB 声卡 | Win/Linux | high | active | 2026-11-11 | 不捆绑 ffmpeg/ffprobe/OmniPickup 二进制 |
| `burn_bundle` | 跨平台 UART 烧录工具的原始 payload：windows/linux 两侧原生烧录程序与启动脚本，供项目级封装调用。 | 通用 | 烧录口 | Win/Linux | high | archived | 2026-04-19 | 2026-11 归档候选，资产清单由 `venusahisiburner` 接管 |
| `device-io` | 设备视图层：USB/串口枚举、板卡分组、端口角色解析、驱动适配、Windows 幽灵设备预览与清理（唯一写操作默认 dry-run）。 | 通用 | USB 串口、CH344/CH348、USB 声卡 | Win/Linux | high | active | 2026-11-11 | 与 `usb-tree`/`clearusb` 重叠，收敛待真机回归 |
| `listenai-play` | 声卡端点查询与播报底层：安装 laid/audio-list、按稳定 Key 或默认设备选路，支持单文件/双设备播放与多后端。 | 通用 | 播报声卡、USB 声卡 | Win/Linux | high | active | 2026-09-21 | 安装脚本唯一来源；播放/采集底层与 `audio-runtime` 重叠 |
| `lstest` | 跨项目设备测试验证与压测框架：profile 驱动日志发现、串口与音频证据采集、时序关联、结果校验，输出可复算的场景回执。 | 通用 | 控制串口、日志串口、播报声卡、录音声卡 | Win/Linux | high | active | 2026-11-06 |  |
| `lstts` | IndexTTS/IndexTTS2 语音合成：文本、表格、云端音色与克隆音色转音频，提供独立 CLI 与 lstts-core Python 包，JSONL 事件流与固定退出码。 | 通用 | — | Win/Linux | high | active | 2026-11-06 | 由 `tts-runtime` 统一入口调用 |

### 能力层（capability）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `arcs-aopu-test` | 奥普/ARCS 离线语音验证与压测：唤醒/ASR 串口日志验证、重启首唤醒、全词表 MP3 覆盖、阈值协议切换与整夜压测。 | ARCS-aopu | 日志串口、播报声卡 | Win | low | legacy | 2026-11-07 | 设备/串口/语料已写明适用边界 |
| `ark-node` | 节点统一入口：环境变量同步（吸收 ark-env）、节点身份与能力探测、安全取件（吸收 ark-mesh）、工件归档调用。 | 通用 | — | Win/Linux | high | active | 2026-11-11 | `ark-env`/`ark-mesh` 无独立仓库，能力并入本仓库 |
| `bootship` | OBU/I2S 录音压测与音频质量分析：设备侧 tinyplay/tinycap、上下电队列、ASIO/XMOS 本地录音、空白/缺失/通道错乱检测与固件对比报告。 | OBU-bootship | 设备串口、I2S 录音、USB 声卡、ASIO | Win/Linux | medium | legacy | 2026-06-16 |  |
| `cskflashtest` | CSK 串口烧录与烧录压测：控制口下电、进 boot、上电，Uart_Burn_Tool 烧录，退出 boot，校验启动日志并统计多轮结果。 | 通用 | 控制串口、烧录口、日志口 | Win | medium | active | 2026-11-07 | 外部依赖 `lstest`（已删内嵌副本） |
| `duya-ota-powercut` | 杜亚双设备 OTA 写入/升级随机断电压测：COM27 共享控制口、COM22/21 日志口、flash.md5 校验与逐轮留证。 | duya-OTA | 控制串口、日志口、电源控制 | Win | low | legacy | 2026-05-25 |  |
| `mars-belt` | MarsPlatform 固件打包→烧录→验证的自治流程：自动决策、自动执行、自动恢复，含平台 API 校验、音频合成与报告/邮件链路。 | MarsPlatform | 烧录口、控制串口、播报声卡 | Win | medium | active | 2026-09-20 |  |
| `mars-moon` | 把需求文档、词表 Excel、tone.h 与固件打成可迁移 bundle，生成 spec/cases/deviceInfo，执行 dry-run、烧录、runner 与结果归档。 | duya-curtain | 烧录口、日志串口、播报声卡 | Win | medium | legacy | 2026-11-07 | bundle 化定位；已改为只依赖 `listenai-play` |
| `mideaSmoke` | 美的烟机/CSK6012 单点烧录与烧录后判定：uut-burn.on/off 进出烧录、Uart_Burn_Tool 烧录整包、校验启动健康与异常重启。 | CSK6012-midea-smoke | 日志口、烧录口、控制口 | Win | low | legacy | 2026-05-29 |  |
| `Polaris` | 语音设备真机 BDD 验证框架：Cucumber 用例 + 固定 runner + Event Runtime 事件断言，输出 PASS/FAIL/BLOCKED/TIMING_AMBIGUOUS。 | 通用 | 日志串口、控制串口、播报声卡、录音声卡 | Win | high | legacy | 2026-11-07 | 2026-11 起不再并列 canonical；能力迁入 `lstest`（NOAH-54 parity 31/31），仓库只读；58MiB 超体积门禁 |
| `polaris-device-validation` | Polaris 旧版真机验证实现（同源 Cucumber/Event Runtime），2026-06 后停更，保留为历史参照。 | 通用 | 日志串口、控制串口、播报声卡、录音声卡 | Win | low | archived | 2026-11-07 | 由 `Polaris` 替代；两仓库曾同名 |
| `power-on-record-check` | 上电→等录音声卡枚举→立即录音→指定声卡播报→收尾断电的多轮压测，输出轮次 CSV/JSON、串口原文与工具日志。 | 通用 | 控制串口、录音声卡、播报声卡 | Win | medium | active | 2026-09-08 |  |
| `scanpen-api-test` | ScanPen 设备 AP/CP 双串口 API 验证与压测：version、trans_start、xtts_start，按正则判定并流式落盘两侧日志。 | ScanPen | AP 口、CP 口 | Win | low | legacy | 2026-06-29 |  |
| `tcl-device-autoburn` | TCL 台架旧烧录入口（节点本地/私有仓库，GitHub 不可读）。 | TCL-ac | 控制串口、烧录口 | Win | low | legacy | 未知（私有/空仓库） | 2026-11 停用，参数映射由 `venusahisiburner` 的 tcl-pvm1005 profile 承担；仓库不删 |
| `tcl-test-sub` | TCL 双麦空调语音验证与压测：唤醒加命令识别长稳、2s/20s 交替间隔、489 条核心命令覆盖、在线交互探测与双串口证据。 | TCL-ac | 日志串口、命令口、播报声卡 | Win | low | active | 2026-11-07 | 设备/串口/语料已写明适用边界；2026-11-07 按现场证据改回 active（TCL-ac 仍在 win009 台架交付，NOAH-20） |
| `Trisolaris` | 离线语音多项目验证：需求→方案/用例→烧录→播放→串口证据→断言，内置小度风扇与好太太晾衣机的项目资产和验证池。 | CSK5062-xiaodu-fan / CSK3022-htt-clothes-airer | 烧录口、日志串口、控制串口、播报声卡 | Win/Linux | medium | legacy | 2026-11-07 | 项目沉淀定位；内嵌 `listenai-play` 整份副本 |
| `tts-runtime` | TTS 统一入口：lstts 云端 IndexTTS / melotts 本地 / mock 离线自检，一个稳定接口。 | 通用 | — | Win/Linux | high | active | 2026-11-11 | URL/token 只从环境变量读取；不含模型与虚拟环境 |
| `venusahisiburner` | VenusA/CSK 与 HISI/HI3863 双芯片统一烧录状态机（preflight/boot/burn/verify/recover/receipt）+ profile 隔离 + 资产清单。 | TCL-ac / CSK6012-midea-smoke | 控制串口、烧录口、日志串口 | Win | high | active | 2026-11-10 | 烧录唯一 canonical；毫秒时间戳待裁决（见 `docs/time-contract.md`） |

### 知识层（knowledge）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `ark-kb` | 能力台账 registry、entries 知识条目、index 索引、schema 与回执/归档契约的唯一事实源。 | 通用 | — | Win/Linux | high | active | 2026-11-11 | 不托管代码资产；改条数必须同步本文件校验脚本 |

### 工具支撑层（tool）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `a4m-Jenkins` | Autodesk Mac 团队 Jenkins 自动化资产：触发 UI/LISP/ARX/Benchmark 测试并收集报告，与语音测试无关。 | AcadMacJenkins | — | Linux | low | archived | 2026-05-12 | 74MB 私有历史工程 |
| `ark-archive` | 结果归档：打包/校验/回执/保留策略，时间契约唯一实现在 `lib/ark_time.py`；文件名时间戳 `YYYYMMDD-HHMMSS`，历史下划线目录只读兼容。 | 通用 | — | Win/Linux | high | active | 2026-11-10 | 校验失败进 `_quarantine/`；口令只从环境变量读 |
| `beep-locator` | 在 PCM/WAV 中定位固定频率蜂鸣（默认 1 秒响+1 秒静+1 秒响），按通道共识输出起止点文件，无需人工真值。 | 通用 | — | Win/Linux | high | active | 2026-07-08 |  |
| `clearusb` | 清理 Windows 已断开的隐藏 USB 串口与设备实例：默认预览，-Apply 才删除，保留驱动包，不碰在线设备。 | 通用 | USB 串口 | Win | medium | active | 2026-10-27 |  |
| `fileball` | 把内网 FTP/NAS 固件 zip 转成 OTA 命令：连 Wi-Fi、FileStation 下载解压、取 OTA bin、上传 OSS、校验公开 URL 并生成 ota.set.url。 | 通用 / OTA 交付 | — | Win | medium | active | 2026-06-23 |  |
| `generate-html-report` | 把日志、统计与测试结果转成结论先行的 HTML 报告：证据链、异常分类、复核口径，可另出邮件内联版。 | 通用 | — | Win/Linux | high | active | 2026-06-26 |  |
| `line-net-monitor` | 按线路配置分段探测防火墙、光猫、电信/腾讯 DNS 与应用层 DNS，每 5 分钟统计丢包与时延并归因到内网/接入网/外网。 | 通用 | 防火墙、光猫 | Win | medium | active | 2026-11-03 |  |
| `listenai-laid-installer` | 已降级为文档入口：说明 `laid` / `audio-list` 安装与验证；安装脚本唯一来源是 `listenai-play`。 | 通用 | 声卡、ListenAI 声卡 | Win/Linux | medium | archived | 2026-11-07 | 由 `listenai-play` 替代；本仓库已无脚本副本 |
| `melotts` | 自包含本地 MeloTTS 中英文语音合成：内置模型、虚拟环境与 NLTK 数据，离线批量输出 WAV。 | 通用 | — | Linux | high | active | 2026-05-08 | `.venv/`、`models/`、`outputs/` 入库 |
| `omni-pickup` | Windows 多 Host API 原始 PCM 录音：按索引或名称选 DirectSound/WASAPI/WDM-KS/ASIO 端点，自定义采样率、通道、位深与时长。 | 通用 | 录音声卡、USB 声卡、ASIO | Win | high | legacy | 2026-09-20 | 录音能力已由 `audio-runtime` 提供，切换待真机回归；`.venv/`、`build/`、`dist/` 入库 |
| `qw-email-handle` | 企业邮箱收发的通用 CLI：SMTP 发信（含附件/HTML），IMAP 只读查收件箱并按发件人、主题、日期、未读状态筛选。 | 通用 | — | Win/Linux | high | active | 2026-06-23 |  |
| `skillhub-sync` | 节点 SkillHub 同步器：canonical 清单 + 节点 profile，校验/暂存/备份/回执，支持 http 传输；不覆盖节点本地修改。 | 通用 | — | Win/Linux | high | active | 2026-11-10 | 远端只读；digest 不符不触碰 |
| `spiderbot` | 企业微信智能表/表格的安全读写：在线快照、备份、增删改与复核，以及讯飞线上问题数据按关键词/创建人去重迁移。 | 通用 | — | Win | medium | active | 2026-05-27 |  |
| `usb-tree` | 按 USB 上游拓扑、PnP 父设备与 Container ID 把 Windows COM、Linux tty 串口和音频端点整理成树，提供 GUI/CLI 与按栏复制导出。 | 通用 | USB Hub、CH344/348、USB 声卡 | Win/Linux | high | active | 2026-10-27 | `.omo/` 会话残留 |

### 编排层（orchestration）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `ark-dispatch` | 只做决策不执行：输入任务+设备条件，查台账输出 plan.v1（选型/顺序/门禁/退出点），禁止网络与设备访问。 | 通用 | — | Win/Linux | high | active | 2026-11-09 | 依赖 `ark-kb` 本地快照；缺失失败关闭（退出码 3） |
| `NoahsArk` | AI 测试平台方案与规格仓库：控制面/节点分工、会话编排、证据 manifest、租约与 C1-C7 门禁设计。 | 通用 | — | Win/Linux | high | active | 2026-11-04 | 唯一带 CI 的仓库 |
| `zhsh` | 局域网分布式 CLI 网关与任务调度：Dashboard、任务队列、PTY 终端桥接、Agent 上报硬件并执行任务、Beacon 一键接入。 | 通用 | — | Win/Linux | high | active | 2026-10-24 |  |

## 依赖关系

按 `depends_skills` 汇总（箭头指向被依赖方）：

```text
ark-dispatch            -> ark-kb
cskflashtest            -> lstest
lstest                  -> lstts, skill-git
mars-moon               -> burn_bundle, listenai-play
NoahsArk                -> lstest
power-on-record-check   -> listenai-play        （随包内嵌副本）
tcl-test-sub            -> listenai-play, trails, skill-creator
test-plan-architect     -> lstest
trails                  -> skill-creator
Trisolaris              -> burn_bundle
tts-runtime             -> lstts, melotts
```

被依赖最多：`lstest`（3）、`listenai-play`（3）、`burn_bundle`（2）、`lstts`（2）、`skill-creator`（2）。2 次档三家并列，所以严格 Top4 实际是 5 个仓库；这批是抽包与兼容性改造的第一优先级。

补充两条事实（避免按旧版误读）：

- `venusahisiburner` 的 `depends_skills` 是 `["无"]`：它的 SKILL.md 与代码里没有引用 `usb-tree` / `clearusb`，枚举与清理能力是各仓库独立实现，没有登记调用关系。
- `burn_bundle` 已 `archived`，但 `Trisolaris` 与 `mars-moon` 仍声明依赖它（历史声明未改）；新流程应走 `venusahisiburner`，这两条依赖只作遗留记录。

## 残留与重复实现

| 仓库 | 现象 | 影响 | 建议 |
|---|---|---|---|
| `cskflashtest` | ~~仓库内嵌完整 `lstest/` 副本~~ | **已修复（2026-11-07）**：删副本，改为外部依赖 `lstest`（已安装包 → `LSTEST_HOME` → 同级目录），lint 复跑 pass | 无 |
| `omni-pickup` | `.venv/`、`build/`、`dist/` 入库（仓库 26MB） | 二进制与虚拟环境入库，跨机不可移植 | 脚本必须走随包 `.venv`；后续改为构建产物不入库 |
| `mars-moon` | README 的 Skill layout 曾列出 `.git/` 条目 | 远端仓库无法跟踪 `.git`；同时原先依赖已归档的 `listenai-laid-installer` | 已清理布局清单；bootstrap 改为只依赖 `listenai-play` |
| `usb-tree` | `.omo/run-continuation/ses_*.json` 入库 | 会话续跑状态进入发布包 | 加入 `.gitignore` |
| `melotts` | `.venv/`、`models/`、`outputs/`、`vendor/` 入库（130MB） | 自包含是设计目标，但 `outputs/` 属历史结果 | 保留模型与 vendor，清理 `outputs/` |
| `NoahsArk` | 唯一带 `.github/` 的仓库 | 其余 45 个仓库无 CI，测试靠本地 `python -m unittest` | 给内核层仓库补最小 CI |
| `a4m-Jenkins` | 74MB 私有历史工程 | 与设备测试无关，拉取成本高 | 保持归档，不下载 |
| `listenai-laid-installer` | ~~仓库内 `install_laid_windows.ps1` / `install_laid_linux.sh` 与 `listenai-play` 同源~~ | **已修复（2026-11-07）**：删脚本副本，降级为文档入口，`status=archived` | 无 |
| `Trisolaris` | `tools/audio/listenai-play` 是 `listenai-play` 的整份副本 | 升级时要同步两份，否则播放行为漂移 | 后续改为外部依赖（需真机回归，本轮未动） |
| `power-on-record-check` | 随包 `scripts/tools/listenai_play.py` 有自己的副本，且旁边没有 `install_laid_*` | `install_laid` 分支在缺脚本时会失败 | 后续改外部依赖；本轮只记录 |
| `Polaris` | 仓库 58MiB，超过 skill-git 50MiB 门禁；代码里写死 `C:\Users\Administrator\.codex\skills\listenai-play\...` | 发布被门禁拦住；换机器/用户后播放路径失效 | 大文件资产外置；播放路径改为配置项或 `LSTEST_HOME` 式解析 |
| `audio-runtime` | 与 `listenai-play`（端点/播放）、`omni-pickup`（Windows 多 Host API 录音）能力重叠 | 同一能力两套实现，行为可能漂移；新代码难以决定调用谁 | 收敛为 `audio-runtime` 单一实现需真机回归，本阶段不动；`omni-pickup` 已记 `legacy` |
| `device-io` | 与 `usb-tree`（拓扑 GUI/CLI）、`clearusb`（幽灵设备清理）能力重叠 | 枚举、分组与清理各有实现，结论可能不一致 | 收敛需真机回归（CH344/CH348 + Windows 幽灵实例），本阶段保留三份 |
| `tts-runtime` | 与 `lstts`/`melotts` 是入口重叠关系（前者是统一入口，后两者是实现） | 同一能力有两个入口，调用口径不一致 | 入口收敛到 `tts-runtime`，`lstts`/`melotts` 保留为引擎实现；切换待回归 |
| `venusahisiburner` | 取代 `burn_bundle`（payload）与 `tcl-device-autoburn`（旧 TCL 入口）—— **已收口（2026-11-11）** | 旧入口仍在台账，误用会绕过 profile 与资产清单校验 | `burn_bundle` 记 `archived`、`tcl-device-autoburn` 记 `legacy` 且 `replaced_by=venusahisiburner`；仓库本身不删 |

## 待确认

1. **~~`Polaris` 的状态~~ → 已裁决（2026-11-11）**：归 `legacy`，`replaced_by=lstest`。依据：可复用能力已迁入 `lstest` 的 profiles/adapters/cases（NOAH-54 parity 31/31），仓库保留只读，不再并列 canonical。
2. **10 个 `legacy` 是“项目收尾/已被取代”判断，不是“代码坏掉”**：`scanpen-api-test`、`arcs-aopu-test`、`bootship`、`mideaSmoke`、`duya-ota-powercut`、`mars-moon`、`Trisolaris`、`Polaris`、`omni-pickup`、`tcl-device-autoburn` 仍可运行；若其中某个项目仍在交付，应改回 `active`。`tcl-test-sub` 已于 2026-11-07 按现场证据（TCL-ac 仍在 win009 台架交付，NOAH-20）改回 `active`。
3. **4 个私有仓库的依赖未核验**（`zhsh`、`fileball`、`qw-email-handle`、`a4m-Jenkins`）：只能读 README，`depends_pkgs` 标为“待核验”，后续有权限时补齐。`tcl-device-autoburn` 是空/私有仓库，只能依据节点侧说明记录。
4. **`Trisolaris` 的定位**：它同时是项目资产库和通用验证池。本版按“项目绑定”记 `legacy`；若定位为长期复用的多项目框架，应改 `active`。
5. **时间契约 A/B 待郑保山裁决（BLOCKED）**：记录层是否允许毫秒。方案 A（记录层统一 `YYYY-MM-DD HH:MM:SS`，毫秒仅限设备层回执）只影响 `venusahisiburner`；方案 B（全线 `YYYY-MM-DDThh:mm:ss.sss`）要改 7 个仓库。当前唯一违约仓库是 `venusahisiburner`。交叉验证另发现 `ark-node` 与 `skillhub-sync` 的判定函数偏宽（接受空格毫秒 / `Z` / 偏移），产物本身合规。详见 [`docs/time-contract.md`](../docs/time-contract.md)。
6. **4 个归档候选待批准打 tag**：`burn_bundle`、`polaris-device-validation`、`listenai-laid-installer`、`a4m-Jenkins`，提案见 [`docs/archive-candidates.md`](../docs/archive-candidates.md)；未获批准前不创建任何 tag、不删仓库。

## 校验

```bash
# 1. JSON 合法性
python3 -m json.tool registry/skills.json > /dev/null

# 2. 46 条、字段齐全、枚举合法、无空字符串
python3 - <<'PY'
import json
d = json.load(open("registry/skills.json"))
F = ["name","repo","layer","status","capability","platform","projects",
     "hardware","depends_skills","depends_pkgs","entry","reuse",
     "scope_note","replaced_by","last_verified"]
assert len(d) == 46, len(d)
assert len({r["name"] for r in d}) == 46
for r in d:
    assert list(r) == F, r["name"]
    assert r["layer"] in {"spec","kernel","capability","knowledge","orchestration","tool"}
    assert r["status"] in {"active","legacy","archived"}
    assert r["reuse"] in {"high","medium","low"}
    assert set(r["platform"]) <= {"windows","linux"} and r["platform"]
    assert r["repo"] == "zjashanda/" + r["name"]
    for k in F:
        v = r[k]
        if k == "replaced_by":
            assert v is None or isinstance(v, str)
        elif isinstance(v, str):
            assert v.strip(), (r["name"], k)
        else:
            assert v and all(isinstance(i, str) and i.strip() for i in v), (r["name"], k)
print("OK 46/46")
PY

# 3. 统计分布（与正文「当前分布」逐项比对）
python3 - <<'PY'
import json, collections
d = json.load(open("registry/skills.json"))
for key in ("status", "layer", "reuse"):
    print(key, dict(collections.Counter(r[key] for r in d)))
PY
```

条目/索引自检用仓库自带的 `python3 tools/kb.py lint`。**本机当前不通过，且与台账无关**，两个原因都要单独修：

1. 缺外部扫描器：`找不到 skill-git 扫描器（scripts/skill_assets.py）`，退出码 3。离线自检可加 `--allow-missing-scanner`（该开关会跳过凭据扫描，公开写入前必须去掉）。
2. 一条预存条目错误：`entry kb-knowledge-4871f3474f8c: $.confidence: 取值 'active' 不在允许集合 ['high','medium','low']`，属 `entries/*.jsonl` 数据问题，不在台账改动范围内。

另有 188 条「证据文件不在本机」警告，属节点侧证据路径，不影响台账校验。

本版仅交付文件，未改动任何被调查仓库，也未推送任何分支。
