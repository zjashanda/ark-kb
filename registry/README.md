# 能力台账 v1

NoahsArk 工作区 35 个仓库的能力、适用设备/项目与可用状态的单一事实源。机器可读版在同目录 [`skills.json`](skills.json)。

本版只做清点，不改任何被调查仓库；所有描述来自仓库 README、`SKILL.md`、顶层目录与最近提交，不包含代码、配置或凭据内容。

## 数据来源与范围

- 采集：GitHub API 只读（`zjashanda`，35 个仓库，其中 4 个私有），采集日期 2026-11-06。
- 逐仓库核对：README、`SKILL.md` 全文、顶层文件清单、最近提交、`requirements.txt` 与关键 payload 目录。
- 私有仓库（`zhsh`、`fileball`、`qw-email-handle`、`a4m-Jenkins`）只能读到 README，依赖标注为“待核验”，不臆造。
- `last_verified` = 本台账静态核验日期（元数据 + 文档 + 依赖清单），**不等于真机验证**。真机结论只能来自节点侧执行证据。

## 字段与口径

| 字段 | 取值 | 说明 |
|---|---|---|
| `layer` | `spec` / `kernel` / `capability` / `knowledge` / `orchestration` / `tool` | 五层架构 + 工具支撑；`knowledge` 本版为空（ark-kb 自身不计入 35 个被清点仓库） |
| `status` | `active` / `legacy` / `archived` | 见下 |
| `reuse` | `high` / `medium` / `low` | 被 ≥2 个 skill 引用或有跨项目独立价值 = high；单一项目群内可复用 = medium；写死型号/协议/硬件 = low |
| `platform` | `windows` / `linux` | 文档里声明或入口脚本实际支持的平台 |
| `entry` | 相对路径 | 主入口；纯文档类 skill 记为 `SKILL.md`，目录型 payload 记为目录/批处理入口 |
| 空集合 | `["无"]` | 为满足“无空字段”，无依赖/无硬件统一写 `["无"]`，便于 grep 与校验 |

**状态判定**（可复核，最近推送日期已列在对照表里）：

- `active`：仍在用或被其他 skill/平台引用，最近 6 个月有更新；纯工具类（`beep-locator`、`melotts`）即使不常更新，只要能力仍可直接使用也记 active。
- `legacy`：项目已收尾、绑定单一项目，但资产与方法论仍可复用；新任务不应默认选它。
- `archived`：已被替代或与方舟无关，只作历史参照。

当前分布：`active` 24 / `legacy` 9 / `archived` 2；分层 `spec` 4 / `kernel` 4 / `capability` 13 / `tool` 12 / `orchestration` 2；复用 `high` 17 / `medium` 11 / `low` 7。

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
| `burn_bundle` | 跨平台 UART 烧录工具的原始 payload：windows/linux 两侧原生烧录程序与启动脚本，供项目级封装调用。 | 通用 | 烧录口 | Win/Linux | high | active | 2026-04-19 |  |
| `listenai-play` | 声卡端点查询与播报底层：安装 laid/audio-list、按稳定 Key 或默认设备选路，支持单文件/双设备播放与多后端。 | 通用 | 播报声卡、USB 声卡 | Win/Linux | high | active | 2026-09-21 |  |
| `lstest` | 跨项目设备测试验证与压测框架：profile 驱动日志发现、串口与音频证据采集、时序关联、结果校验，输出可复算的场景回执。 | 通用 | 控制串口、日志串口、播报声卡、录音声卡 | Win/Linux | high | active | 2026-11-06 |  |
| `lstts` | IndexTTS/IndexTTS2 语音合成：文本、表格、云端音色与克隆音色转音频，提供独立 CLI 与 lstts-core Python 包，JSONL 事件流与固定退出码。 | 通用 | — | Win/Linux | high | active | 2026-11-06 |  |

### 能力层（capability）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `arcs-aopu-test` | 奥普/ARCS 离线语音验证与压测：唤醒/ASR 串口日志验证、重启首唤醒、全词表 MP3 覆盖、阈值协议切换与整夜压测。 | ARCS-aopu | 日志串口、播报声卡 | Win | low | legacy | 2026-06-26 |  |
| `bootship` | OBU/I2S 录音压测与音频质量分析：设备侧 tinyplay/tinycap、上下电队列、ASIO/XMOS 本地录音、空白/缺失/通道错乱检测与固件对比报告。 | OBU-bootship | 设备串口、I2S 录音、USB 声卡、ASIO | Win/Linux | medium | legacy | 2026-06-16 |  |
| `cskflashtest` | CSK 串口烧录与烧录压测：控制口下电、进 boot、上电，Uart_Burn_Tool 烧录，退出 boot，校验启动日志并统计多轮结果。 | 通用 | 控制串口、烧录口、日志口 | Win | medium | active | 2026-11-06 | 内嵌 `lstest/` 副本 |
| `duya-ota-powercut` | 杜亚双设备 OTA 写入/升级随机断电压测：COM27 共享控制口、COM22/21 日志口、flash.md5 校验与逐轮留证。 | duya-OTA | 控制串口、日志口、电源控制 | Win | low | legacy | 2026-05-25 |  |
| `mars-belt` | MarsPlatform 固件打包→烧录→验证的自治流程：自动决策、自动执行、自动恢复，含平台 API 校验、音频合成与报告/邮件链路。 | MarsPlatform | 烧录口、控制串口、播报声卡 | Win | medium | active | 2026-09-20 |  |
| `mars-moon` | 把需求文档、词表 Excel、tone.h 与固件打成可迁移 bundle，生成 spec/cases/deviceInfo，执行 dry-run、烧录、runner 与结果归档。 | duya-curtain | 烧录口、日志串口、播报声卡 | Win | medium | legacy | 2026-04-23 | README 清单残留 `.git/` |
| `mideaSmoke` | 美的烟机/CSK6012 单点烧录与烧录后判定：uut-burn.on/off 进出烧录、Uart_Burn_Tool 烧录整包、校验启动健康与异常重启。 | CSK6012-midea-smoke | 日志口、烧录口、控制口 | Win | low | legacy | 2026-05-29 |  |
| `Polaris` | 语音设备真机 BDD 验证框架：Cucumber 用例 + 固定 runner + Event Runtime 事件断言，输出 PASS/FAIL/BLOCKED/TIMING_AMBIGUOUS。 | 通用 | 日志串口、控制串口、播报声卡、录音声卡 | Win | high | active | 2026-07-02 |  |
| `polaris-device-validation` | Polaris 旧版真机验证实现（同源 Cucumber/Event Runtime），2026-06 后停更，保留为历史参照。 | 通用 | 日志串口、控制串口、播报声卡、录音声卡 | Win | low | archived | 2026-06-04 | 由 `Polaris` 替代 |
| `power-on-record-check` | 上电→等录音声卡枚举→立即录音→指定声卡播报→收尾断电的多轮压测，输出轮次 CSV/JSON、串口原文与工具日志。 | 通用 | 控制串口、录音声卡、播报声卡 | Win | medium | active | 2026-09-08 |  |
| `scanpen-api-test` | ScanPen 设备 AP/CP 双串口 API 验证与压测：version、trans_start、xtts_start，按正则判定并流式落盘两侧日志。 | ScanPen | AP 口、CP 口 | Win | low | legacy | 2026-06-29 |  |
| `tcl-test-sub` | TCL 双麦空调语音验证与压测：唤醒加命令识别长稳、2s/20s 交替间隔、489 条核心命令覆盖、在线交互探测与双串口证据。 | TCL-ac | 日志串口、命令口、播报声卡 | Win | low | legacy | 2026-07-28 |  |
| `Trisolaris` | 离线语音多项目验证：需求→方案/用例→烧录→播放→串口证据→断言，内置小度风扇与好太太晾衣机的项目资产和验证池。 | CSK5062-xiaodu-fan / CSK3022-htt-clothes-airer | 烧录口、日志串口、控制串口、播报声卡 | Win/Linux | medium | legacy | 2026-06-04 |  |

### 工具支撑层（tool）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `a4m-Jenkins` | Autodesk Mac 团队 Jenkins 自动化资产：触发 UI/LISP/ARX/Benchmark 测试并收集报告，与语音测试无关。 | AcadMacJenkins | — | Linux | low | archived | 2026-05-12 | 74MB 私有历史工程 |
| `beep-locator` | 在 PCM/WAV 中定位固定频率蜂鸣（默认 1 秒响+1 秒静+1 秒响），按通道共识输出起止点文件，无需人工真值。 | 通用 | — | Win/Linux | high | active | 2026-07-08 |  |
| `clearusb` | 清理 Windows 已断开的隐藏 USB 串口与设备实例：默认预览，-Apply 才删除，保留驱动包，不碰在线设备。 | 通用 | USB 串口 | Win | medium | active | 2026-10-27 |  |
| `fileball` | 把内网 FTP/NAS 固件 zip 转成 OTA 命令：连 Wi-Fi、FileStation 下载解压、取 OTA bin、上传 OSS、校验公开 URL 并生成 ota.set.url。 | 通用 / OTA 交付 | — | Win | medium | active | 2026-06-23 |  |
| `generate-html-report` | 把日志、统计与测试结果转成结论先行的 HTML 报告：证据链、异常分类、复核口径，可另出邮件内联版。 | 通用 | — | Win/Linux | high | active | 2026-06-26 |  |
| `line-net-monitor` | 按线路配置分段探测防火墙、光猫、电信/腾讯 DNS 与应用层 DNS，每 5 分钟统计丢包与时延并归因到内网/接入网/外网。 | 通用 | 防火墙、光猫 | Win | medium | active | 2026-11-03 |  |
| `listenai-laid-installer` | 在 PowerShell、bash、zsh profile 中安装并验证 laid 命令，Windows 附带 audio-list 端点列表与稳定 USB 标识。 | 通用 | 声卡、ListenAI 声卡 | Win/Linux | medium | legacy | 2026-07-29 | 由 `listenai-play` 替代 |
| `melotts` | 自包含本地 MeloTTS 中英文语音合成：内置模型、虚拟环境与 NLTK 数据，离线批量输出 WAV。 | 通用 | — | Linux | high | active | 2026-05-08 | `.venv/`、`models/`、`outputs/` 入库 |
| `omni-pickup` | Windows 多 Host API 原始 PCM 录音：按索引或名称选 DirectSound/WASAPI/WDM-KS/ASIO 端点，自定义采样率、通道、位深与时长。 | 通用 | 录音声卡、USB 声卡、ASIO | Win | high | active | 2026-09-20 | `.venv/`、`build/`、`dist/` 入库 |
| `qw-email-handle` | 企业邮箱收发的通用 CLI：SMTP 发信（含附件/HTML），IMAP 只读查收件箱并按发件人、主题、日期、未读状态筛选。 | 通用 | — | Win/Linux | high | active | 2026-06-23 |  |
| `spiderbot` | 企业微信智能表/表格的安全读写：在线快照、备份、增删改与复核，以及讯飞线上问题数据按关键词/创建人去重迁移。 | 通用 | — | Win | medium | active | 2026-05-27 |  |
| `usb-tree` | 按 USB 上游拓扑、PnP 父设备与 Container ID 把 Windows COM、Linux tty 串口和音频端点整理成树，提供 GUI/CLI 与按栏复制导出。 | 通用 | USB Hub、CH344/348、USB 声卡 | Win/Linux | high | active | 2026-10-27 | `.omo/` 会话残留 |

### 编排层（orchestration）

| 仓库 | 能干什么 | 项目 | 硬件 | 平台 | 复用 | 状态 | 最近推送 | 备注 |
|---|---|---|---|---|---|---|---|---|
| `NoahsArk` | AI 测试平台方案与规格仓库：控制面/节点分工、会话编排、证据 manifest、租约与 C1-C7 门禁设计。 | 通用 | — | Win/Linux | high | active | 2026-11-04 | 唯一带 CI 的仓库 |
| `zhsh` | 局域网分布式 CLI 网关与任务调度：Dashboard、任务队列、PTY 终端桥接、Agent 上报硬件并执行任务、Beacon 一键接入。 | 通用 | — | Win/Linux | high | active | 2026-10-24 |  |

## 依赖关系

按 `depends_skills` 汇总（箭头指向被依赖方）：

```text
lstest                  -> lstts, skill-git
cskflashtest            -> lstest
test-plan-architect     -> lstest
NoahsArk                -> lstest
power-on-record-check   -> listenai-play        （随包内嵌副本）
tcl-test-sub            -> listenai-play, trails, skill-creator
Trisolaris              -> burn_bundle
mars-moon               -> burn_bundle, listenai-play, listenai-laid-installer
trails                  -> skill-creator
```

被依赖最多：`lstest`（3）、`listenai-play`（3）、`burn_bundle`（2）、`skill-creator`（2）。这四个是抽包与兼容性改造的第一优先级。

## 残留与重复实现

| 仓库 | 现象 | 影响 | 建议 |
|---|---|---|---|
| `cskflashtest` | 仓库内嵌完整 `lstest/` 副本；而 `SKILL.md` 明写“不复制、不修改 lstest，运行时当作公共库” | 文档与事实矛盾，副本会随 lstest 升级漂移 | 删除副本，改为依赖 `lstest`；本版只记录，不动代码 |
| `omni-pickup` | `.venv/`、`build/`、`dist/` 入库（仓库 26MB） | 二进制与虚拟环境入库，跨机不可移植 | 脚本必须走随包 `.venv`；后续改为构建产物不入库 |
| `mars-moon` | README 的 Skill layout 仍列出 `.git/` 条目 | 远端仓库无法跟踪 `.git`，说明打包清点把本地目录带进了清单 | 清理清单与本地打包流程 |
| `usb-tree` | `.omo/run-continuation/ses_*.json` 入库 | 会话续跑状态进入发布包 | 加入 `.gitignore` |
| `melotts` | `.venv/`、`models/`、`outputs/`、`vendor/` 入库（130MB） | 自包含是设计目标，但 `outputs/` 属历史结果 | 保留模型与 vendor，清理 `outputs/` |
| `NoahsArk` | 唯一带 `.github/` 的仓库 | 其余 34 个仓库无 CI，测试靠本地 `python -m unittest` | 给内核层仓库补最小 CI |
| `a4m-Jenkins` | 74MB 私有历史工程 | 与设备测试无关，拉取成本高 | 保持归档，不下载 |

## 待确认

1. **`Polaris` 的状态**：issue 正文把 `Polaris` 举例为 `legacy`，但采集事实是 2026-07-02 仍在更新、`polaris-device-validation` 已明确由它替代（`功能对应关系.md` 也定为“A 为主”）。本版按 `active` 记录；若确认要归 `legacy`，只需改这一条。
2. **9 个 `legacy` 是“项目收尾”判断，不是“代码坏掉”**：`tcl-test-sub`、`scanpen-api-test`、`arcs-aopu-test`、`bootship`、`mideaSmoke`、`duya-ota-powercut`、`mars-moon`、`Trisolaris`、`listenai-laid-installer` 仍可运行；若其中某个项目仍在交付，应改回 `active`。
3. **4 个私有仓库的依赖未核验**（`zhsh`、`fileball`、`qw-email-handle`、`a4m-Jenkins`）：只能读 README，`depends_pkgs` 标为“待核验”，后续有权限时补齐。
4. **`Trisolaris` 的定位**：它同时是项目资产库和通用验证池。本版按“项目绑定”记 `legacy`；若定位为长期复用的多项目框架，应改 `active`。

## 校验

```bash
# 1. JSON 合法性
python -m json.tool registry/skills.json > /dev/null

# 2. 35 条、字段齐全、枚举合法、无空字符串
python - <<'PY'
import json
d = json.load(open("registry/skills.json"))
F = ["name","repo","layer","status","capability","platform","projects",
     "hardware","depends_skills","depends_pkgs","entry","reuse",
     "scope_note","replaced_by","last_verified"]
assert len(d) == 35, len(d)
assert len({r["name"] for r in d}) == 35
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
print("OK 35/35")
PY
```

本版仅交付文件，未改动任何被调查仓库，也未推送任何分支。
