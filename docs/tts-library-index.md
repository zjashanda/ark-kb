# TTS 资产索引：ark-kb 只存可搜索元数据

本文说明 ark-kb 在 1006 可复用 TTS 音频库中的边界。规格见
`result/tts-library-proposal.md`（NOAH-66），契约字段以
`schema/asset-entry.v1.json` 为准，本文不另立字段名。

## 1. 边界：索引不是库

| 对象 | 真源 | 职责 |
|---|---|---|
| 音频本体、`manifest.json`、锁、`_incoming`、outbox | `asset-tools` 的 `tts-library` | 发布、取件、校验、幂等、ACL 执行 |
| 可搜索索引条目 | ark-kb 的 `entries/asset/entries.jsonl` | 让人和智能体先找到线索 |
| 派生音频（重采样/增益/降噪） | 任务目录 `work/audio/` 或 `result/audio/` | 不回归共享库 |

一句话：**ark-kb 命中只是线索，不是资产存在的证明**。取件前必须调用
`asset-tools tts-library fetch/verify`，复核 `manifest.json` 与 `audio.sha256`。
索引未命中也不等于「1006 库里没有」，只说明本索引没有登记。

因此 `asset-query` 的返回里固定带 `index_only=true` 与提示文案；任何调用方都不得把
索引路径当成可直接读取的文件地址，也不得据此跳过 SHA 校验。

## 2. 索引条目字段

一条记录一行 JSONL，落在 `entries/asset/entries.jsonl`，按 `asset_id` 稳定排序。
索引文件 `index/asset-index.json` 由工具生成，不要手改。

| 字段 | 必填 | 含义 |
|---|---|---|
| `schema` | 是 | 固定 `ark.tts-asset-entry.v1` |
| `asset_id` | 是 | `tts-<key16>` 或版本化 `tts-<key16>-vN` |
| `cache_key` | 是 | 完整缓存键 sha256（64 位小写十六进制），精确命中唯一权威 |
| `audio_sha256` | 是 | 音频内容哈希；取件后由调用方自行复核 |
| `quality` | 是 | `formal / candidate / evidence_gap` |
| `status` | 是 | `active / stale / superseded` |
| `scope` | 是 | `{visibility, projects[], nodes[]}`，即 ACL 摘要 |
| `language` | 是 | 语言标签，如 `ZH`、`EN` |
| `voice` | 是 | 音色名；只有参考音频时写 `ref:<sha16>` |
| `engine` | 是 | 合成引擎名，如 `lstts`、`melotts` |
| `library_path` | 是 | 相对 1006 库根的受控路径，禁止绝对路径与 `..` |
| `created_at` | 是 | 资产首次登记时间，北京时间 `YYYY-MM-DD HH:MM:SS` |
| `updated_at` | 是 | 索引条目最近一次刷新时间，同一格式 |
| `summary` | 是 | 脱敏短摘要，最多 300 字，只由元数据拼装 |
| `superseded_by` | 是 | 被哪个资产取代；非 `superseded` 时为 `null` |

`library_path` 的正则拒绝以 `/` 开头、盘符、反斜杠和任何 `..` 片段。它只是
「相对库根的定位提示」，调用方必须把它交给 `asset-tools`，不得自行拼接访问。

## 3. 登记：`asset-record`

```bash
# 正常登记（manifest 由 asset-tools publish 产出）
python3 tools/kb.py asset-record --root . --asset /path/to/manifest.json --json

# 从标准输入登记
cat manifest.json | python3 tools/kb.py asset-record --root . --asset - --json

# 只演算不落盘
python3 tools/kb.py asset-record --root . --asset manifest.json --dry-run
```

登记前会做四件事，任何一项失败都返回非零且**不写任何文件**：

1. 读 JSON 并校验 `ark.tts-asset.v1` 必需字段；
2. 校验 `asset_id`、`cache_key`、`audio.sha256`、时间格式、`scope` 组合；
3. 用 skill-git 的 `SECRET_PATTERNS` 扫描 manifest，命中凭据直接拒绝（退出码 3）；
4. 检查 `library_path` 是受控相对路径。

幂等规则：同一 `asset_id` 且同一 `audio_sha256` 重放，只刷新 `updated_at`，
不新增行、不改变已有状态；状态只允许降级（`active → stale → superseded`），
不允许从 `stale` 或 `superseded` 静默升回 `active`。

## 4. 版本化与 `--supersede`

同一 cache key 出现不同 SHA 时，`asset-tools` 会发布 `tts-<key16>-v2`。
ark-kb 不自己发明版本号，也不接受同一 `asset_id` 换 SHA：

```text
[v2 先独立登记] 两个条目并存，旧条目仍是 active
[v2 + --supersede] 旧条目 status=superseded，superseded_by=新资产 ID
```

```bash
# 省略值：取 manifest.supersedes；没有则推断上一版本
python3 tools/kb.py asset-record --root . --asset v2.manifest.json --supersede

# 显式指定被取代的旧资产
python3 tools/kb.py asset-record --root . --asset v2.manifest.json --supersede tts-<key16>
```

没有 `--supersede` 时，旧条目不会被改写。已经指向别的后继时再次指定，会以
`ASSET_SUPERSEDE_CONFLICT` 拒绝，避免索引里出现来回改指向的漂移。

## 5. 检索：`asset-query`

```bash
python3 tools/kb.py asset-query --root . --voice 付小春 --language ZH --json
python3 tools/kb.py asset-query --root . --engine lstts --quality formal --top 5
python3 tools/kb.py asset-query --root . --asset-id tts-<key16> --json
python3 tools/kb.py asset-query --root . --cache-key <64hex> --json
python3 tools/kb.py asset-query --root . --sha256 <64hex> --json
```

| 参数 | 作用 |
|---|---|
| `--asset-id` / `--cache-key` / `--sha256` | identity 精确匹配，结果标 `match=exact` |
| `--voice` / `--language` / `--engine` | 软条件筛选，结果标 `match=candidate` |
| `--quality` | 按质量档过滤，不改变 ACL |
| `--scope` | 按 `public / project / restricted` 过滤 |
| `--project` / `--node` | ACL 上下文，不匹配的条目直接不返回 |
| `--status` | 显式按状态过滤 |
| `--include-stale` | 连同 `stale` 与 `superseded` 一起返回，仅供人工核查 |
| `--top` | 最多返回条数，默认 10 |

默认只返回 `active`。`stale`、`superseded` 默认不出现；`--include-stale` 打开后
两者都返回，但**不能**作为任务输入，只能用于人工核查与迁移审计。

排序按「精确匹配优先、质量高优先、状态活跃优先、`asset_id` 字典序」稳定输出。
查询是只读的：不写命中计数、不改条目、不创建索引。

## 6. 质量与状态生命周期

| 值 | 含义 | 自动复用 |
|---|---|---|
| `formal` | 通过质检、证据齐全 | 允许 |
| `candidate` | 可用但证据不足 | 默认拒绝，需人工确认 |
| `evidence_gap` | 缺少证据链 | 拒绝 |

| 状态 | 含义 | 检索默认 |
|---|---|---|
| `active` | 当前有效 | 返回 |
| `stale` | 过期或长期零引用 | 不返回 |
| `superseded` | 已被新版本取代 | 不返回 |

状态变化只由显式登记驱动：新 manifest 写 `status`，或 `--supersede` 标记旧条目。
ark-kb 不按时间自动降级，也不做 GC；过期判定由维护任务给出新 manifest 后重登记。

## 7. ACL 与作用域

| `scope.visibility` | 读取条件 |
|---|---|
| `public` | 任何人可查 |
| `project` | `--project` 命中 `scope.projects` 之一 |
| `restricted` | `--project` 命中 `projects`，或 `--node` 命中 `nodes` |

`project` 必须有非空 `projects`；`restricted` 必须有 `projects` 或 `nodes`。
不满足条件的条目不会出现在结果里，也不会通过 `--scope` 绕过 ACL。

## 8. ark-kb 永不存储的内容

- 音频字节、音频文件、base64 片段；
- 原始文本、`text.normalized` 全文（摘要只由语言/音色/引擎/质量等元数据拼装）；
- token、AK/SK、密码、私钥、cookie；
- 1006 的绝对路径、主机名加端口、可直接访问的 URL；
- 源文件清单、上传暂存目录、锁文件。

`asset-record` 只提取元数据字段；manifest 里的 `text`、`audio.bytes` 等都不会进入
`entries.jsonl`。凭据扫描命中时整份拒绝，不做「先写入再清洗」。

## 9. 与既有契约的关系

- `docs/kb-sync.md` 描述的是知识条目的回流入库（`receipt.v1 → entry.v1`）。
  资产索引是**另一条独立通道**：它不产生知识条目，不参与 `record` 的去重与提升，
  也不影响 `by-device`、`by-capability`、`by-skill` 三个索引。
- `asset-record` 与 `record` 共享同一套安全口径：凭据扫描器缺失即失败关闭，
  命中即拒绝写入。
- `kb.py index` 会同时重建知识索引与 `index/asset-index.json`；
  `kb.py lint` 会校验资产条目的 schema、重复 `asset_id`、`superseded_by` 指向、
  ACL 组合以及资产索引是否漂移。
- 与 `asset-tools` 的分工：`tts-library` 负责 key/lookup/fetch/publish/verify/index，
  ark-kb 只登记「已经发布成功的资产」的搜索元数据；发布失败或只在 outbox 里的资产
  不得登记。

## 10. 自检

```bash
python3 -m unittest discover -s tests -q
python3 tools/secret_scan.py .
python3 ../ark-node/tools/time_lint.py tools/kb.py schema/asset-entry.v1.json \
  docs/tts-library-index.md tests/test_asset_index.py
```

时间字段统一为北京时间 `YYYY-MM-DD HH:MM:SS`，空格分隔、秒精度，不带时区后缀。
