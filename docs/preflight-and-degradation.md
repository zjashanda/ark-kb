# 任务前置知识检查与降级判定

本文把「知识查询」到「任务能不能开工」这一步写成可执行判定，避免每个 Agent 各写一份口径。
判定实现在 `tools/kb_policy.py`，只有标准库依赖，可离线运行。

## 为什么需要判定，而不只是查询

查询只回答「有没有命中」。真正影响执行的是三件事同时成立：

1. 命中条目是 `active`，不是 `pending`/`stale`/`superseded`；
2. 服务声明的 `source_commit` 与 `indexed_commit` 相等且 `freshness=fresh`；
3. 本次任务的风险等级允许使用当前这份知识。

前两条由服务返回，第三条属于消费方必须自己执行的规则。缺了第三条，高风险任务会拿旧知识开工。

## 判定矩阵

| freshness | 普通任务 | 高风险任务 |
|---|---|---|
| `fresh` | `PROCEED` | `PROCEED` |
| `stale` | `PROCEED_WITH_CACHE`（回执写 `freshness=stale` + 所用 commit） | `BLOCKED_KB_STALE` |
| `unavailable` | 有未过期缓存 → `PROCEED_WITH_CACHE`；否则 `GIT_FALLBACK` | `BLOCKED_KB_UNAVAILABLE` |
| `unknown` | 同 `unavailable` | `BLOCKED_KB_UNAVAILABLE` |

「高风险」指烧录、真机操作、发布、删除、权限变更这类不可逆或有对外影响的操作。
「未过期」以服务声明的 `stale_after_seconds` 为界，缓存自己记录 `recorded_at` 与 `age_seconds`。

`unknown` 与 `unavailable` 同等处理：没有成功同步记录，就等于没有可信来源。

## 用法

```bash
# 判定
python3 tools/kb_policy.py --risk high --freshness stale --cache cache.json --json

# 判定矩阵自检（离线，10 条）
python3 tools/kb_policy.py --selftest
```

作为库调用：

```python
from kb_policy import evaluate, build_preflight, render_markdown

decision = evaluate(risk="high", freshness=freshness, cache=cache)
if decision["decision"].startswith("BLOCKED"):
    raise SystemExit(decision["decision"])

preflight = build_preflight(task=..., freshness=..., source_commit=..., indexed_commit=...,
                           entries=hits, recorded_at=now_text())
open("preflight.md", "w", encoding="utf-8").write(render_markdown(preflight))
```

`build_preflight` 产出 `ark.knowledge-preflight.v1`，内容只有三样东西：知识快照、
命中条目、每条要读的结论与证据引用。它可以直接贴进任务 `plan.md` 的「知识查询」一节。

## 回执要求

- `PROCEED` / `PROCEED_WITH_CACHE`：回执必须带 `knowledge_snapshot`（commit、freshness、条目 id、时间）；
- 用了缓存或 Git 兜底：额外写 `freshness=stale` / `kb_unavailable=true` 与缓存时间；
- `BLOCKED_KB_STALE` / `BLOCKED_KB_UNAVAILABLE`：写 `blocked_code`、`source_commit`、`indexed_commit`，
  不许把 BLOCKED 写成 PASS。

## 边界

- 判定只管「能不能用这份知识」，不判断知识本身对不对；条目结论的正确性仍靠证据与审核。
- `pending` 不是 `active`：判定不把 `pending` 当结论，是否允许参考由任务风险等级决定，默认不参考。
- 本工具不访问网络，也不读服务以外的状态；`freshness` 必须来自当次服务响应，不许手填。
