# `reuse: high` 的使用关系：谁在用、怎么调用

> 台账要求：`reuse: high` 的每个 skill 都要能说清"谁在用、怎么调用"。
> 本文件给出口径：**A = 代码/配置级调用（可 grep 复现）**、**B = 仅文档/契约声明**、**C = 仓库内无调用方（独立 CLI 或人工/现场调用）**。
> 证据日期 2026-11-07；只读仓库现状，不含真机结论。C 级不等于没人用，只代表"当时 35 个仓库里找不到调用方"，现场脚本不在仓库内。

## 被仓库直接调用（有被依赖方）

| skill | 谁在用 | 怎么调用 | 证据 |
|---|---|---|---|
| `lstest` | `cskflashtest` | `from lstest.scripts.core/profile/runtime/timeline/interaction_acceptance/environment_cleanup/result_stats/serial_recovery import ...`；外部依赖，按"已安装包 → `LSTEST_HOME` → 同级目录"解析 | A：`cskflashtest/scripts/run.py`、`run_multi.py`、`scripts/lstest_env.py` |
| `lstest` | `test-plan-architect` | 只引用 profile/case contract 口径，不 import 代码 | B：台账 `depends_skills`，`test-plan-architect` 为规范类仓库 |
| `lstest` | `NoahsArk` | 只引用"四类产物 + 回执"契约 | B：台账 `depends_skills`，`NoahsArk` 为规格仓库无运行时代码 |
| `lstts` | `lstest` | `lstts_core.client.request_audio/extract_wav`、`lstts_core.audio.inspect_wav`、`lstts_core.voices.resolve_voice` | A：`lstest/scripts/audio_synthesis.py:17-22` |
| `lstts` | `Trisolaris` | `run_tts` 只走 `lstts_core`（NOAH-10 已删除 edge-tts 兜底） | A：`Trisolaris` TTS 改造提交 `e7eb8a1` |
| `lstts` | `tcl-test-sub` | 语料重生成脚本 `scripts/regen_audio.py` | A：`tcl-test-sub` 提交 `3c4e1db` |
| `lstts` | `arcs-aopu-test` | 语料重生成脚本 | A：`arcs-aopu-test` 提交 `70e418b` |
| `listenai-play` | `Polaris` | 直接调用 `~/.codex/skills/listenai-play/scripts/listenai_play.py`；JSON 产物由 `json_artifact_parser` 解析 | A：`Polaris/.../device_adapter.py:342`、`scripts/run_interrupt_injection.py:372` |
| `listenai-play` | `tcl-test-sub` | `~/.codex/skills/listenai-play/scripts/listenai_play.py` | A：`tcl-test-sub/SKILL.md:59` |
| `listenai-play` | `mars-moon` | `tools/audio_playback.py` 调用播放脚本 | A：`mars-moon/tools/audio_playback.py` |
| `listenai-play` | `cskflashtest` | 通过 `lstest` 的 `listenai_play.py` 播报（不自带副本） | A：`cskflashtest/scripts/run.py` `lstest_script("listenai_play.py")` |
| `listenai-play` | `Trisolaris` | 仓库内 `tools/audio/listenai-play` 是整份副本 | A（副本方式）：`Trisolaris/tools/audio/listenai-play/` |
| `listenai-play` | `power-on-record-check` | 台账声明随包内嵌，未在本轮复核代码 | B |
| `burn_bundle` | `Trisolaris` | 调用仓库内 `tools/burn_bundle/run_fan_burn.ps1` / `.sh` | A：`Trisolaris/references/fullflow-validation-method.md:118-119` |
| `burn_bundle` | `mars-moon` | bundle 内使用烧录工具 payload | B：台账 `depends_skills` |
| `skill-creator` | `trails` | 规范引用（skill 编写规范） | B |
| `skill-creator` | `tcl-test-sub` | 规范引用 | B |
| `skill-git` | `lstest` | 发布门禁：`scripts/skill_git.py lint-skill` | A：`lstest` 台账 `depends_skills`，发布流程使用 |
| `trails` | `tcl-test-sub` | 结果目录/task.log/CSV 约定 | B |
| `test-plan-architect` | 无仓库调用方 | 人工：`python scripts/validate_profilepack.py <pack>` | C |
| `usb-tree` | 无仓库调用方 | 人工/现场：`scripts/usbTree.ps1` | C |
| `beep-locator` | 无仓库调用方 | 人工/现场：`python scripts/locate_beep.py` | C |
| `omni-pickup` | 无仓库调用方 | 人工/现场：`src/OmniPickup.py` | C |
| `generate-html-report` | 无仓库调用方 | 人工：按 `SKILL.md` 流程生成报告 | C |
| `melotts` | 无仓库调用方 | 人工/现场：`scripts/synth.py`（离线合成） | C |
| `qw-email-handle` | 无仓库调用方 | 人工/现场：`scripts/mailbox_tool.py` | C |
| `NoahsArk` | 无仓库把它当运行依赖 | 规格仓库，`docs/VERSIONING.md` | C |
| `zhsh` | 无仓库调用方 | 平台部署：`start_all.bat` | C |
| `Polaris` | 无仓库调用方 | 真机执行入口：`python satellite/cucumber-agent-testing/scripts/run_task.py -- ...` | C |

## 结论

1. **有运行时耦合的只有 6 个**：`lstest`（← cskflashtest）、`lstts`（← lstest/Trisolaris/tcl/arcs）、`listenai-play`（← Polaris/tcl/mars-moon/cskflashtest）、`burn_bundle`（← Trisolaris）、`skill-git`（← lstest）、`skill-creator`/`trails`（← tcl）。
2. **其余 high 是"独立 CLI + 人工调用"**，没有仓库级依赖，所以去重时不能拿"有没有人 import"当唯一判据；要区分"库"和"工具"。
3. **需要盯的两处副本**：`Trisolaris/tools/audio/listenai-play`（整份副本）、`Polaris` 里写死的 `~/.codex/skills/listenai-play/...` 绝对路径。前者建议后续改外部依赖，后者建议改配置项。
4. **调用方缺证据的**：`power-on-record-check`、`mars-moon → burn_bundle`、`NoahsArk/test-plan-architect → lstest` 都只有声明没有代码级证据，已在表里标 B，不要当 A 用。
