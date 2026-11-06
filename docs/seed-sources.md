# 首批条目的来源

2026-11-06 建立 v1 时写入的种子条目，全部有可复核来源；没有一条是凭印象写的。
GitHub 事实在 2026-11-06 通过 `git ls-remote` 与 GitHub API 实际核对过。

| 条目 | 类型 | 来源 | 复核方式 |
|---|---|---|---|
| `kb-knowledge-f23119d4a433` cskflashtest 内嵌 lstest/scripts 副本 | knowledge | `zjashanda/cskflashtest@aeab2f1d`，目录 `lstest/` 下只有 `scripts/` | `GET /repos/zjashanda/cskflashtest/contents/lstest` 返回 `[scripts]`；`lstest/SKILL.md` 返回 404 |
| `kb-knowledge-72b7856e1559` omni-pickup 把 .venv 提交进了仓库 | knowledge | `zjashanda/omni-pickup@001d8e11`，根目录 `.venv/` | `GET /repos/zjashanda/omni-pickup/contents/.venv` 返回 200；仓库体积约 25MiB |
| `kb-knowledge-49d383c0b8a1` melotts 提交了 .venv，仓库约 127MiB | knowledge | `zjashanda/melotts@1472514a`，根目录 `.venv/` | `GET /repos/zjashanda/melotts/contents/.venv` 返回 200；`size=130304` KB |
| `kb-knowledge-0e8f85cddf7a` win009 台架的执行通道约束 | knowledge | Multica issue `NOAH-8` 的背景与只读边界 | issue 正文（控制面到台架网段无路由、必须隐藏窗口执行） |
| `kb-knowledge-1cbdc4c52cf2` TCL 被测设备的硬件构成 | knowledge | Multica issue `NOAH-8` 的“背景资料”段 | issue 正文（双 MCU、8 通道 UAC、`uut-switch1` 复位） |
| `kb-knowledge-d81c3d1877cc` 运行时语音合成统一走 lstts | knowledge | Multica issue `NOAH-10` 的目标与约束 | issue 正文 |
| `kb-method-677defa1dbca` 判定红线：BLOCKED/INVALID/NEEDS_REVIEW 不得写成 PASS | method | Multica issue `NOAH-9` 的判定红线 | issue 正文 |
| `kb-knowledge-60d65219fd43`、`kb-method-0205df2c95f8`、`kb-method-9b11d61e6bed`、`kb-run-42681662dc2c` | 自检 | `docs/receipts/20261106-kb-selftest/run.receipt.json` | 回执证据目录内 2 个文件，哈希已校验 |

## 维护口径

- 种子条目全部是 `pending`：只被一轮观察/一个 issue 支撑，没有经过两次独立执行验证，不升级为 `active`。
- GitHub 类事实绑定到具体 commit；上游变化后应新增条目并用 `record --supersede` 指向新条目，不直接改旧条目。
- issue 类事实绑定 issue 编号；issue 被推翻时同样走 supersede，保留历史。
- 内网地址、设备编号、账号没有入库：win009 条目只写“台架所在网段无路由”，不写具体网段或主机地址。
