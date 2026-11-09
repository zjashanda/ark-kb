# 节点环境变量同步（ark-env）

> 一次部署、一处修改、节点自取。适用于任意数量节点。

## 架构

```
真源  /srv/storage/ark/env/env.json      （linux003，仅一份）
  ↓ publish.sh
发布  /srv/storage/ark/dist/ark/          （HTTP 只读）
  ↓ HTTP + Basic Auth
节点  ark-env.ps1 / ark-env.sh → 比对 SHA256 → 只写差异 → 自检
```

## 入口

| 网段 | 入口 |
|---|---|
| `10.11.63.0/24` | `http://10.11.63.24:8090`（宿主机转发 → linux003:8080） |
| `10.210.8.0/24` | `http://10.210.8.205:8080`（直连） |

脚本自动探测，两个都不通则报错退出，不静默降级。

## 节点执行（Windows）

```powershell
irm http://10.11.63.24:8090/ark/ark-env.ps1 -OutFile "$env:TEMP\ark-env.ps1"
& "$env:TEMP\ark-env.ps1" -Pass '<口令>' -Diff
& "$env:TEMP\ark-env.ps1" -Pass '<口令>' -Apply
Remove-Item "$env:TEMP\ark-env.ps1"
```

## 节点执行（Linux）

```bash
curl -fsSL http://10.11.63.24:8090/ark/ark-env.sh -o /tmp/ark-env.sh
bash /tmp/ark-env.sh --pass '<口令>' --diff
bash /tmp/ark-env.sh --pass '<口令>' --apply
rm -f /tmp/ark-env.sh
```

## 改值与轮换

1. 编辑 `/srv/storage/ark/env/env.json`（改 `__version`）
2. `sudo bash /srv/storage/ark/dist/publish.sh /srv/storage/ark/env`（或 env 目录下的 publish.sh）
3. 各节点执行 `-Apply`：只写变化的键，重复执行 `changed=0`

## 变量清单

| 键 | 用途 |
|---|---|
| `GITHUB_TOKEN` | skill-git 推送 |
| `ACCESS_KEY_ID` / `ACCESS_KEY_SECRET` | OSS（skill-git / lstts / fileball 共用） |
| `LSTTS_TTS_TOKEN` | IndexTTS 合成 |
| `EMAIL_PASSWORD` | 企业邮箱授权码 |
| `NAS_ACCOUNT` / `NAS_PASSWORD` | 群晖 FileStation |
| `STORAGE_HOST` / `STORAGE_USER` / `STORAGE_PASSWORD` | 归档服务器 |
| `ARCH_ENV_VERSION` | 由脚本写入，判断节点版本 |

## 安全约定

- `env/` 权限 `750 root:sambashare`，`env.json` 为 `640`；**禁止 chmod 777**
- 口令只存服务器 `/etc/ark-http.env`（600）与节点 `~/.config/ark/auth.json`（600）
- 服务只允许 `GET`，无目录列表，日志不记录 `Authorization`
- 环境变量是进程启动快照：**改完必须重开进程**

## 归档（NOAH-31）

```
/srv/storage/ark/results/<node>/<project>/<run_id>/
```
走 `scp -P 10027` 或 `rsync`；摘要永久、原始日志 30 天。
