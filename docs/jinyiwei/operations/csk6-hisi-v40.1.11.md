# CSK6+HISI V40.1.11 锦衣卫操作卡

## 适用范围

- 芯片：CSK6 + HiSilicon WS63
- 项目：`cskflashtest / VenusA+WS63`
- 固件：V40.1.11（执行时必须重新校验包 SHA）
- 节点：win003/win005 等当前任务节点；不得复用其他节点 COM 映射

## 前置

1. 查询 8091 `capability=burn-and-power-verify`、`device=CSK6`、项目和固件，记录快照。
2. 枚举板卡和 CH344，生成 `port-map.json`。
3. VCOM 控制口固定 115200；A/B/C/D 波特率从当前项目 profile 读取。
4. 预检 profile：`csk6.burn.invocation`、`success_markers`、`expected_partitions`。
5. 固件包下载、SHA-256、解包清单和内部版本全部一致后才可烧录。

## 角色

```text
A  CSK6/CSK7 统一日志；CSK7 也可从 A 烧录
B  CSK6 烧录
C  HISI/上位机日志与烧录
D  CSK6 CP 日志
VCOM 控制和上下电，115200
```

## 单台执行

- CSK6 走 B 口；CSK7 走 A 口；HISI 走 C 口；D 采 CSK6 CP 日志。
- CSK 成功需要：工具 exit 0、CONNECT WITH CHIP SUCCESS、CHIP TYPE、WRITE SIZE、设备 MD5、FLASH DOWNLOAD SUCCESS、控制回执和版本回读全部满足 profile。
- HISI 记录 optLog 全文、分区集合和烧写结果；分区不一致判 `NEEDS_REVIEW`，不能直接 PASS。
- 上下电：VCOM off → 等待 → on，记录 `switch_idx*_set` 回执。
- 上电后同时采集 CSK 日志与 HISI 日志；0 字节启动日志判 FAIL。

## 并行与稳定性

- CSK 多台并行最大 4，设备端口必须互斥。
- HISI 并行默认 4，失败时按 4→2 降级，记录降级原因；不能把降级后的结果写成默认并行通过。
- `topology=module_only` 与 `baseboard_present` 必须分开判定；仅模组下已知 SPI/baseboard 13 秒周期复位可记 `EXPECTED_TOPOLOGY_BEHAVIOR`，不等于整机稳定性 PASS。
- 出现 panic/assert/watchdog、非预期复位、版本不一致或采集器失效时转 FAIL/NEEDS_REVIEW。

## 结果与回流

- 原始日志和音频证据上传 8090，回执含 `uri/bytes/sha256`。
- 结构化事件包括 `burn.pass`、`power.on.ack`、`hisi.partition_mismatch`、`reset.observed`、`audio.playback`。
- 新波特率、marker、恢复方法或项目差异先建锦衣卫知识候选，审核通过后才更新公共手册。
- 本卡不是当前任务的 COM 映射；当前映射只存在于任务目录 `port-map.json`。
