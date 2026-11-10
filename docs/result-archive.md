# 结果归档与回执入库

一次压测跑完后要做三件事：把结果搬上存储服务器、生成回执、把回执写进知识库。三步都在节点侧完成，ECS 上的调度与书吏不直连存储。

## 路径约定

```
/srv/storage/ark/
  results/<node>/<project>/<run_id>/     # 原始结果 + manifest.json
  receipts/<node>/<project>/<run_id>/run.receipt.json
  artifacts/                             # 固件、音频等大文件，不混进结果目录
  _quarantine/<node>/<run_id>-<ts>/      # 校验不通过整批隔离
  env/                                   # 分发配置，与结果隔离
```

节点在前、项目在后。节点清单不写死在任何脚本里：新节点第一次归档时按 `<node>` 自建目录，不需要改配置。

## 三步

1. **归档**（`ark-archive.sh` / `ark-archive.ps1`，见 NOAH-31）：上传到 `.incoming-<run_id>-<ts>` 暂存区，远端逐文件重算 sha256，通过才 `mv` 进正式路径；不通过整批进 `_quarantine`。只复制不移动，源数据不动。
2. **生成回执**（`tools/ark-receipt.sh` / `tools/ark-receipt.ps1` → `tools/ark_receipt.py`）：从**已归档的** `manifest.json` + `summary_final.json` 生成 `run.receipt.v1`。`evidence_dir` 一律写存储上的绝对路径，绝不写节点本地临时路径。本地还留着结果目录时顺带复核哈希，不一致直接退出 3。
3. **入库**：把回执交给 `kb.py record`。回执在两台机器上（存储与节点）都取不到文件，`kb.py` 走「路径 + 哈希」登记，逐文件写入 `evidence_files` 给出的 ref，`verified=false`——这是存储型证据的预期形态，不是告警。

## 用法

Linux / macOS：

```bash
export ARK_STORAGE_HOST=10.11.63.24 ARK_STORAGE_PORT=10027 ARK_STORAGE_USER=administrator
export ARK_STORAGE_SSH_PASS=<口令>        # 只在环境变量里，不落盘不进回执
tools/ark-receipt.sh --node win009 --project tcl-r5 --run-id 20261102_090644_wake_recognition \
  --task "..." --skill lstest --skill-version "lstest-debug 20261102" --upload
```

Windows PowerShell 5.1：

```powershell
$env:ARK_STORAGE_SSH_PASS = '<口令>'
tools\ark-receipt.ps1 -Node win009 -Project tcl-r5 -RunId 20261102_090644_wake_recognition `
  -Task "..." -Skill lstest -SkillVersion "lstest-debug 20261102" -Upload
```

两个入口同一套参数、同一条输出：`RECEIPT_AT / RECEIPT_SHA256 / RECEIPT_VERIFIED: OK`。加 `--dry-run`（PS 用 `-DryRun`）只打印不落盘。

退出码：`0` 成功、`2` 参数或源数据缺失、`3` 哈希不一致、`4` 上传或读回失败。

## 回执字段

在 `schema/receipt.v1.json` 之上多带三样：`evidence_files[]`（path + sha256 + bytes，供 kb 登记每条存储路径）、`archive{}`（node/project/storage_root/archived_at/source_dir/manifest_sha256）、`notes`。`totals` 取自 summary，`failures` 由 summary 的失败轮次与串口错误推导，没有就留空数组。

## 目录权限

`/srv/storage/ark/{results,receipts}` 是 `root:sambashare 2755`，节点用户建不了顶层目录。节点第一次归档时用自身管理口令 `sudo` 建出 `<node>/<project>/<run_id>` 并 `chgrp sambashare` + `chmod 2775`（脚本里 `ensure_dir`，输出 `PROVISION:` 行），之后同节点再归档不需要提权。要让任意新节点零提权自建，需把 `receipts/` 改成 2775 或加 ACL——这是权限变更，先申请再执行。

## 保留策略（郑保山 2026-11-09 确认，方案 B）

`summary_final.json`、`rounds.csv`、回执、`manifest.json` 永久保留；`serial_logs/` 与原始日志保留 30 天。清理用 `ark-prune.sh`（默认 dry-run，列出清单后再 `--apply`），清理规则：

```bash
find /srv/storage/ark/results -path "*/serial_logs/*" -type f -mtime +30 -delete
find /srv/storage/ark/results -path "*/tool.log" -type f -mtime +90 -delete
```

## 实例

`docs/receipts/20261102-win009-wake/run.receipt.json` 是 win009 `20261102_090644_wake_recognition` 批次的真实回执：15 个文件、208999 字节、`result=pass`，`evidence_dir` 指向 `/srv/storage/ark/results/win009/tcl-r5/20261102_090644_wake_recognition`，入库后 15 条证据全部登记为存储路径。
