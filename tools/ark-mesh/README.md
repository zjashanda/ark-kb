# ark-mesh：局域网节点文件互通

节点缺固件 / 烧录工具 / 语料 / 测试物料时，不再直接回 BLOCKED，而是按固定顺序自动去别的节点取件，
把文件落到本次任务的资产目录，逐字节校验后写 `artifact-manifest.json`；只有所有来源都失败，
才输出一份“试过哪些来源、各自什么错、下一步怎么办”的失败报告。

## 一句话用法

```bash
# 看全网节点与制品台账
python3 ark_fetch.py status

# 按台账取件到某台机器的任务资产目录（源端与目的端都校验 sha256）
python3 ark_fetch.py fetch --name tcl-csk7-firmware \
    --dest-node pvm1005 --dest 'D:\zhsh\workspace\tasks\noah-38\assets'

# 没登记过的文件，按“节点 + 路径”直连取
python3 ark_fetch.py fetch --source win010 --path 'D:\burn\V12.1.25\CSK\Uart_Burn_Tool.exe' \
    --sha256 2ea640… --dest-node pvm1005 --dest 'D:\zhsh\workspace\tasks\noah-38\assets'

# 把制品归档进 1006 存储（长期存放），并自动把它登记成最低优先级的来源
python3 ark_fetch.py archive --name uart-burn-tool-v12
```

## 取件顺序（硬规则）

1. **本地缓存**：`~/.cache/ark-mesh/<sha256前16位>/<文件名>`，命中即用，不重复搬运。
2. **台账里的节点来源**：按 `priority` 从小到大逐个尝试，单个来源默认超时 30s（`--timeout`）。
3. **1006 长期存储**：`/srv/storage/ark/artifacts/<project>/<version>/`，由 `archive` 自动登记为最低优先级。
4. 全部失败 → 写 `fetch-failure-report.json`，`verdict=BLOCKED`，退出码 3。

邮件附件、NAS、skillhub 属于“把文件先落进某个节点”的上游取件流程，不归本工具管；本工具从节点开始接管。

## 安全红线

- **凭据永不自动搬运**：文件名或路径命中 `.env` / `password` / `token` / `secret` / `key` / `pem` / `p12` /
  `credential` / `id_rsa` / `npmrc` / `netrc` / `cookie` / `auth.json` / `git-credentials` 一律拒绝，退出码 4。
  凭据必须在目标节点用官方方式单独配置。
- **只读源端**：只做 `scp` 读，不写、不改、不删来源文件和缓存。
- **不改源文件名、不做格式转换**：按字节搬运，源端与目的端都算 sha256。
- **搬运期间不碰设备**：不占用串口、不启动烧录，取件与烧录是两个阶段。
- **凭据只经环境变量**：需要口令的节点在 `nodes.<name>.auth = "sshpass-env"`，口令从环境变量读取，
  不落盘、不打印、不进日志。

## 台账（来源索引）

默认读 `$ARK_MESH_CONFIG`，否则 `~/.config/ark/mesh-sources.json`（与脚本同目录的 `sources.json` 次之）。
**台账含内网地址，只放本机与内网存储，不进公开仓库**；公开仓库里只放 `sources.example.json` 模板。

```json
{
  "schema": "ark-mesh-sources.v1",
  "cache": {"dir": "~/.cache/ark-mesh"},
  "nodes": {
    "win010": {"kind": "windows", "host": "10.0.0.10", "port": 22, "user": "administrator",
               "base_dir": "D:\\zhsh\\workspace\\artifacts"},
    "storage1006": {"kind": "linux", "host": "10.0.0.20", "port": 10027, "user": "administrator",
                    "base_dir": "/srv/storage/ark/artifacts",
                    "auth": "sshpass-env", "pass_env": "ARK_STORAGE_SSH_PASS"}
  },
  "artifacts": {
    "hisi-ws63-firmware": {
      "name": "hisi-ws63-firmware", "project": "noah-37", "version": "V8-H363T20-WFMV206.111.1.16",
      "bytes": 3694352, "sha256": "ed2eaf…", "filename": "V8-H363T20-WFMV206.111.1.16.bin",
      "locations": [
        {"node": "win010", "path": "D:\\zhsh\\workspace\\artifacts\\V8…bin", "priority": 1},
        {"node": "win002", "path": "D:\\zhsh\\workspace\\artifacts\\V8…bin", "priority": 2}
      ]
    }
  }
}
```

登记新发现的东西（工具、固件、语料都按这个登记，别只留在聊天记录里）：

```bash
python3 ark_fetch.py index --name burn-tool-x --project noah-37 --version V1.0 \
    --sha256 <hash> --bytes <n> --filename Uart_Burn_Tool.exe \
    --node win010 --path 'D:\burn\V1.0\Uart_Burn_Tool.exe' --priority 1
```

## 产物

目的目录（`--dest`）下三样东西：

| 文件 | 内容 |
|---|---|
| 制品本体 | 原名原样 |
| `artifact-manifest.json` | 追加式清单，见下 |
| `fetch-failure-report.json` | 只在失败时出现 |

`artifact-manifest.json`：

```json
{
  "schema": "ark-artifact-manifest.v1",
  "artifacts": [
    {
      "name": "tcl-csk7-firmware",
      "project": "noah-37",
      "version": "V0.0.41",
      "source_node": "win010",
      "source_path": "D:\\zhsh\\workspace\\artifacts\\HAS_TCL_CSK7_HI3863_LZX_20261103_TEST_V0.0.41.zip",
      "destination": "pvm1005:D:\\zhsh\\workspace\\tasks\\noah-38\\assets\\HAS_TCL_CSK7_HI3863_LZX_20261103_TEST_V0.0.41.zip",
      "bytes": 41306610,
      "sha256": "1e703ad8…",
      "fetched_at": "2026-11-09T19:58:32+08:00",
      "destination_sha256_verified": true
    }
  ],
  "updated_at": "2026-11-09T19:58:36+08:00"
}
```

按 `sha256 + destination` 去重，重复取同一件不会写重复条目。

失败报告 `fetch-failure-report.json` 至少包含：`attempts[]`（每条来源的节点、路径、结果、
错误原文、耗时）、`next_steps[]`、`verdict=BLOCKED`。报告同时打印到 stdout。

## 传输模型（今天怎么跑）

`ark_fetch.py` 用本机 `ssh`/`scp` 连目标节点，因此**必须在一台能免密登录全网的机器上跑**。
目前只有 `bszT14` 持有全网公钥，它是 relay：所有取件都由它发起，文件经它中转再推到目的节点。

长期做法是给每台节点互相装公钥（`bootstrap.ps1` / `bootstrap.sh` 会打印要追加的公钥），
然后把台账放到节点本地、在那台节点直接跑同一份脚本，不需要改任何代码。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 用法/配置错误（台账不存在、节点未登记、缺口令环境变量） |
| 3 | 所有来源都失败（BLOCKED，已写失败报告） |
| 4 | 命中凭据红线，拒绝搬运 |

## 上机（bootstrap）

```powershell
# Windows 节点
powershell -ExecutionPolicy Bypass -File bootstrap.ps1 -ConfigUrl '\\10.11.63.24\storage\ark\mesh\sources.json'
```

```bash
# Linux 节点
bash bootstrap.sh --config /mnt/ark/mesh/sources.json
```

bootstrap 只做三件事：建 `~/.config/ark`（Windows 为 `%USERPROFILE%\.config\ark`）、
把 `ark_fetch.py` 与本机台账副本放好、跑一次 `status` 自检并把结果打印出来。
**新节点上线只跑 bootstrap，不改调度侧代码。**

## 测试

```bash
python3 -m unittest discover -s tests -p 'test_ark_fetch.py' -v
```

单测离线跑，不连任何节点。

## 已知环境坑（实测）

- **Windows 上用子进程调 ssh 会卡死**：Win32-OpenSSH 在 stdout/stderr 是管道时不退出（PowerShell 里手跑同一条命令正常）。
  `ark_fetch.py` 在 Windows 上一律把子进程输出写临时文件、并带 `CREATE_NO_WINDOW`，不弹窗也不卡死。
- **端口转发节点探测自己会超时**：`10.11.63.24:10023/10026` 这类 NAT 映射口没有回环，节点自己连自己的映射口会
  卡到超时。台账里给这类节点加 `local: true` 或直接用本机路径，不必把它当远端探。
- **节点之间今天没有互信公钥**：非 relay 节点跑 `status` 会得到 `Permission denied (publickey,password)`，这是真实
  结果而不是工具故障；按 `bootstrap` 打印的公钥互相授权后即变 PASS。
