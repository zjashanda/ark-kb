# 归档候选提案（2026-11-11）

> **本文件是提案，不是执行记录。任何 tag 创建、README 冻结横幅、仓库转移或删除，均需郑保山在 NOAH-55 下明确批准；未批准前不执行任何一项。**
>
> 依据：`registry/skills.json` 的 `status` / `replaced_by` 与 `registry/README.md`「残留与重复实现」表。SHA 为台账记录值，打 tag 前必须用 `git ls-remote` 复核一次。

冻结统一形态（批准后对每个候选执行）：

1. 在默认分支顶部打 tag `freeze-20261111`（注解 tag，说明冻结原因与替代仓库）。
2. README 顶部加一段冻结横幅：「已冻结（2026-11-11），不再接受功能变更；替代仓库 → `<repo>`」；无替代的在横幅里写明「历史外部工程，无替代」。
3. **不删除仓库、不转私有、不归档 GitHub Archive 状态**——只打 tag 与改 README。

回滚方式（任一候选）：删除 tag 即可，README 横幅用一次 `git revert` 回退；不改动历史提交，因此没有任何数据不可恢复。

---

## 1. burn_bundle

- **仓库**：`zjashanda/burn_bundle`
- **当前 SHA**：`33483b4`（台账记录值，打 tag 前复核）
- **归档依据**：`status=archived`、`replaced_by=venusahisiburner`；`scope_note` 已写明「2026-11 起归档候选，资产清单由 venusahisiburner 接管」。纯 UART payload，被 `venusahisiburner` 的 `venusa-uart` 阶段（`Uart_Burn_Tool -b -p -f -a`）覆盖。
- **前置条件**：
  - [x] 替代实现可用：`venusahisiburner` 的 `scripts/burn.py` 与 `assets/manifest.json` 已覆盖双芯片烧录与资产登记。
  - [x] 台账状态已改：`skills.json` 中 `burn_bundle.status=archived`、`replaced_by="venusahisiburner"`。
  - [x] 长期无更新：最后推送 2026-04-19（超过 6 个月）。
  - [ ] 依赖方已迁移：**未满足**。`Trisolaris` 与 `mars-moon` 的 `depends_skills` 仍声明 `burn_bundle`（历史声明未改）。
  - [ ] 真机回归：**未做**。`venusahisiburner` 的 TCL profile 有实测记录，但 Media/美的 profile 仍是 `draft`。
- **冻结形态**：tag `freeze-20261111`；README 顶部横幅「已冻结，替代仓库 → `zjashanda/venusahisiburner`」。
- **回滚**：删 tag；横幅 `git revert`。
- **明确不删除仓库**：保留 payload 与历史启动脚本，供追溯 2026-04 前的烧录参数。

## 2. polaris-device-validation

- **仓库**：`zjashanda/polaris-device-validation`
- **当前 SHA**：`502f2d2`（台账记录值，打 tag 前复核）
- **归档依据**：`status=archived`、`replaced_by=lstest`（2026-11-11 由 `Polaris` 改为 `lstest`）。`Polaris` 自身已转 `legacy`，可复用能力迁入 `lstest` 的 profiles/adapters/cases（NOAH-54 parity 31/31），本仓库是更早的一代实现（2026-06 后停更）。
- **前置条件**：
  - [x] 替代链路确定：`polaris-device-validation` → `lstest`（经 `Polaris` 的 parity 已验证）。
  - [x] 台账状态已改：`status=archived`。
  - [x] 命名冲突已解：两仓库曾共用 frontmatter `name=polaris-device-validation`，`Polaris` 已改名 `name=Polaris`。
  - [x] 无在册依赖：`skills.json` 中没有任何仓库的 `depends_skills` 指向本仓库。
  - [ ] 真机回归：**未做**（本阶段不做，见「残留与重复实现」表）。
- **冻结形态**：tag `freeze-20261111`；README 顶部横幅「已冻结，替代仓库 → `zjashanda/lstest`（经 `Polaris` 迁移）」。
- **回滚**：删 tag；横幅 `git revert`。
- **明确不删除仓库**：保留 2026-06 前的用例与配置格式，用于追溯旧结果。

## 3. listenai-laid-installer

- **仓库**：`zjashanda/listenai-laid-installer`
- **当前 SHA**：`64fd1dd`（台账记录值，打 tag 前复核）
- **归档依据**：`status=archived`、`replaced_by=listenai-play`。安装脚本副本已于 2026-11-07 删除（与 `listenai-play` 同源），仓库降级为文档入口；`listenai-play` 是安装脚本唯一来源。
- **前置条件**：
  - [x] 替代实现可用：`listenai-play` 的 `scripts/` 提供 `laid` / `audio-list` 安装与验证。
  - [x] 台账状态已改：`status=archived`、`replaced_by="listenai-play"`。
  - [x] 副本已删：本仓库已无 `install_laid_windows.ps1` / `install_laid_linux.sh`，不存在两处不同步的问题。
  - [x] 无在册依赖：无仓库 `depends_skills` 指向本仓库。
  - [ ] 现场脚本改指向：**待确认**。按旧路径 `scripts/*` 调用安装器的现场脚本需改指 `listenai-play`，本阶段未逐台核查。
- **冻结形态**：tag `freeze-20261111`；README 顶部横幅「已冻结，替代仓库 → `zjashanda/listenai-play`（安装脚本唯一来源）」。
- **回滚**：删 tag；横幅 `git revert`。
- **明确不删除仓库**：文档入口仍可读，避免现场按旧链接 404。

## 4. a4m-Jenkins

- **仓库**：`zjashanda/a4m-Jenkins`（**私有**）
- **当前 SHA**：`e6836f7`（台账记录值，打 tag 前复核）
- **归档依据**：`status=archived`；Autodesk Mac 团队 Jenkins 资产（UI/LISP/ARX/Benchmark），与方舟设备测试无交集；仓库 74MB，拉取成本高。台账已注明「不下载不执行」。
- **前置条件**：
  - [x] 与方舟无关已确认：`projects` 仅 `AcadMacJenkins`，无设备测试依赖。
  - [x] 台账状态已改：`status=archived`。
  - [x] 无在册依赖：无仓库 `depends_skills` 指向本仓库。
  - [x] 不新增拉取：README 与台账均要求「保持归档，不下载」。
  - [x] 私有仓库可打 tag：写权限在 `zjashanda` 账号，无需开源审批。
- **冻结形态**：tag `freeze-20261111`；README 顶部横幅「已冻结（2026-11-11），历史外部工程，无替代仓库」。不公开、不迁移。
- **回滚**：删 tag；横幅 `git revert`。
- **明确不删除仓库**：保留历史 Jenkins 资产，删除会造成不可恢复的团队资产丢失。

---

## 批准与执行边界

- 批准人：郑保山；批准载体：NOAH-55 issue 评论（企业微信转达的授权同等有效，但必须在 issue 留痕：批准人 / 时间 / 原话）。
- 批准后执行顺序：复核 SHA → 打 annotation tag → 推 tag → 改 README 横幅 → 回填本文件状态。四步任一步失败即停，不跳步。
- 本阶段**不做**：不删仓库、不改默认分支、不动 GitHub Archive 状态、不改任何仓库的代码。
