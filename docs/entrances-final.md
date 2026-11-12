# 最终入口清单（收口版）

> 状态：2026-11-11 收口（NOAH-55）。上承 NOAH-45 盘点（41 资产）与 Stage 1–4 交付。
> 口径：Git 仓库 = 源码事实源；节点 SkillHub = 运行副本；本台账 = 能力/知识索引。

## 14 个 canonical 入口

| # | 仓库 | 层 | 职责边界 | 本次收口 commit | 依赖 skill |
|---|---|---|---|---|---|
| 1 | `venusahisiburner` | capability | VenusA/CSK 与 HISI/HI3863 统一烧录状态机 | `8bd7ddd`（R4 按方案 A 落地） | 无 |
| 2 | `lstest` | kernel | 跨项目设备测试/压测框架（吸收 Polaris 能力） | `b69cc58` | lstts、skill-git |
| 3 | `listenai-play` | kernel | 声卡端点查询与播报底层 | `84944c2`（未改） | 无 |
| 4 | `mars-belt` | capability | MarsPlatform 固件打包→烧录→验证自治流程 | `92b3178`（未改） | 无 |
| 5 | `usb-tree` | tool | USB 上游拓扑 / PnP 父设备 / Container ID 解析 | `b439ae8`（未改） | 无 |
| 6 | `clearusb` | tool | 清理 Windows 隐藏 USB 串口与设备实例 | `9d47e86`（未改） | 无 |
| 7 | `device-io` | kernel | 设备视图层：枚举、分组、端口角色、驱动适配 | `256e0b4`（未改） | 无 |
| 8 | `audio-runtime` | kernel | 音频视图与执行层：端点、媒体探测、多 Host 播放 | `384031c`（未改） | 无 |
| 9 | `tts-runtime` | capability | TTS 统一入口（lstts 云端 / melotts 本地） | `4b01f36`（未改） | lstts、melotts |
| 10 | `skill-git` | spec | Skill 发布门禁：建仓校验、凭据扫描、dry-run | `d35ad9a`（未改） | 无 |
| 11 | `ark-dispatch` | orchestration | 只做决策不执行，输出 plan.v1 | `a76ac8e` | ark-kb |
| 12 | `ark-kb` | knowledge | 台账、知识条目、索引、schema、回执工具 | 本文件所在提交（自引用） | 无 |
| 13 | `ark-node` | capability | 节点统一入口：环境变量同步（吸收 ark-env）、节点身份与能力探测 | `8b5fb65` | 无 |
| 14 | `asset-tools` | kernel | 资产发现/manifest/校验/内容寻址缓存/供给 | `429442f`（未改） | 无 |

「未改」= 本次收口未新增提交，沿用既有 main；SHA 为收口时实测远端 main。

## 平台基础设施（不入 `skills[]`，不自同步）

| 仓库 | commit | 为什么不进默认同步清单 |
|---|---|---|
| `ark-archive` | `fe4d4bf` | 归档/回执的服务端组件，跑在存储节点由运维部署，不作为节点 skill 安装 |
| `skillhub-sync` | `4e47218` | 同步工具自身；它消费清单，不能由清单分发自己 |

两者仍受时间契约与台账管辖，台账里都是 `active`。

## SkillHub 默认同步清单

`manifests/canonical.json` 的 `skills[]` 严格等于上表 14 条（顺序即上表顺序），全部 `sync=canonical`、`visibility=public`。

profile 覆盖：

| profile | 平台 | 收录 | 排除 |
|---|---|---|---|
| `bsz-t14` | linux | skill-git、ark-kb、ark-dispatch、lstest、ark-node、asset-tools | — |
| `win-bench` | windows | venusahisiburner、lstest、listenai-play、usb-tree、clearusb、skill-git、device-io、audio-runtime、tts-runtime | mars-belt |
| `template` | 通用 | skill-git | — |

已知空白：`mars-belt` 目前没有任何 profile 收录（win-bench 显式排除）。MarsPlatform 台架若需同步，应在该机器上单独建 profile，不在通用 profile 里扩散。

## 旧入口收口（只读引用，不再默认同步）

| 旧入口 | 处理 | 承接者 |
|---|---|---|
| `Polaris` | disabled + 台账 `status=legacy`，`replaced_by=lstest` | `lstest`（NOAH-54 parity 31/31 agreed） |
| `tcl-device-autoburn` | disabled，停用；私有空仓库，不再读取 | `venusahisiburner` |
| `burn_bundle` | disabled；归档候选 | `venusahisiburner` |
| `polaris-device-validation` | disabled；归档候选 | `lstest` |
| `listenai-laid-installer` | disabled；归档候选 | `listenai-play` |
| `ark-env` / `ark-mesh` | disabled；无独立仓库 | `ark-node` |
| `a4m-Jenkins` | disabled；归档候选（私有） | 无（Jenkins 现场保留） |

归档候选的冻结形态、前置条件与回滚方式见 `docs/archive-candidates.md`：只打 `freeze-20261111` annotation tag 并在 README 挂横幅，不删除任何仓库；破坏性删除需单独授权。

## 依赖图（canonical 内，按台账 `depends_skills`）

```
lstest        → lstts, skill-git
tts-runtime   → lstts, melotts
ark-dispatch  → ark-kb
```

其余 10 个入口的 `depends_skills` 均为 `["无"]`。

说明两点：

- `usb-tree` / `clearusb` 是台架编排时由调用方（人或 dispatch 的步骤模板）先行执行的工具，不在 `venusahisiburner` 代码里 import；实测该仓库源码无 `usb-tree`/`clearusb`/`ark-mesh` 引用，故不写进 `depends_skills`，避免台账声明不存在的代码依赖。
- `listenai-play` 与 `mars-belt` 的关系是 mars-belt 内嵌了一份 `listenai-play`/`listenai-laid-installer` 的调用副本，属打包内容而非安装依赖，台账按「不重复登记」处理。

## 验收证据（2026-11-11 实测）

| 仓库 | 命令 | 结果 |
|---|---|---|
| `ark-kb` | `registry/README.md` 校验脚本 | `OK 44/44`（status active30/legacy10/archived4） |
| `ark-dispatch` | `python3 -m unittest tests.test_dispatch` | 74 tests OK；`dispatch.py rules` → OK routing.v1 |
| `skillhub-sync` | `python3 -m unittest tests.test_skill_sync`；`tools/time_lint.py --gate --root .` | 28 tests OK；0 violation / 18 files |
| `ark-archive` | `python3 -m unittest discover -s tests` | 47 tests OK |
| `ark-node` | `python3 -m unittest`；`tools/time_lint.py` | 58 tests OK (skipped=1)；0 violation / 35 files |
| `lstest` | `python3 -m unittest discover -s tests` | 193 tests OK (skipped=2) |
| 跨仓库时间样例 | `python3 tools/time_contract_check.py --repos ../ --only samples` | 6/6 仓库判定一致，退出码 0（R4 已按方案 A 落地，`venusahisiburner` 已改造） |

时间契约全文与 R4 落地记录见 `docs/time-contract.md`。
