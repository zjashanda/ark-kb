"""凭据扫描适配层。

规则不在这里重复实现：真正扫描的 `SECRET_PATTERNS` 来自 `skill-git`
仓库的 `scripts/skill_assets.py`（发布门禁与知识库共用同一份规则）。
本模块只负责定位、加载、应用，并在扫描器缺失时**失败而不是放行**。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SCANNER_RELATIVE = Path("scripts") / "skill_assets.py"
DEFAULT_HOMES = (
    Path("~/.codex/skills/skill-git"),
    Path("~/.codex/skill-git-repos/skill-git"),
)


class ScannerUnavailable(RuntimeError):
    """找不到 skill-git 的扫描器。公开仓库写入前必须扫描，因此不能静默继续。"""


def candidate_homes(root: Path | None = None, explicit: str | None = None) -> list[Path]:
    homes: list[Path] = []
    if explicit:
        homes.append(Path(explicit).expanduser())
    env_home = os.environ.get("SKILL_GIT_HOME")
    if env_home:
        homes.append(Path(env_home).expanduser())
    if root is not None:
        # 常见布局：skill-git 与 ark-kb 并排 checkout
        homes.append(root.parent / "skill-git")
        homes.append(root / "vendor" / "skill-git")
    homes.extend(path.expanduser() for path in DEFAULT_HOMES)
    return homes


def resolve_home(root: Path | None = None, explicit: str | None = None) -> Path:
    tried = []
    for home in candidate_homes(root, explicit):
        scanner = home / SCANNER_RELATIVE
        tried.append(str(scanner))
        if scanner.is_file():
            return home
    raise ScannerUnavailable(
        "找不到 skill-git 扫描器（scripts/skill_assets.py）。已尝试："
        + "、".join(tried)
        + "。请用 --skill-git-home 或 SKILL_GIT_HOME 指定 skill-git 仓库。"
    )


def load_patterns(home: Path) -> tuple:
    scanner = home / SCANNER_RELATIVE
    spec = importlib.util.spec_from_file_location("ark_kb_skill_assets", scanner)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御性分支
        raise ScannerUnavailable(f"无法加载扫描器模块：{scanner}")
    module = importlib.util.module_from_spec(spec)
    # dataclass 装饰器依赖模块已注册，先登记再执行
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 扫描器损坏时同样不能放行
        raise ScannerUnavailable(f"加载扫描器失败：{scanner}：{exc}") from exc
    patterns = getattr(module, "SECRET_PATTERNS", None)
    if not patterns:
        raise ScannerUnavailable(f"扫描器未提供 SECRET_PATTERNS：{scanner}")
    return tuple(patterns)


class SecretScanner:
    """把 skill-git 的正则清单套到文本上；命中时只回规则序号，不回显明文。"""

    def __init__(self, patterns: tuple, home: Path) -> None:
        self.patterns = patterns
        self.home = home

    def scan_text(self, text: str) -> list[int]:
        hits = []
        for index, pattern in enumerate(self.patterns, start=1):
            if pattern.search(text):
                hits.append(index)
        return hits

    def scan_files(self, paths) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for path in paths:
            path = Path(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits = self.scan_text(text)
            if hits:
                result[str(path)] = hits
        return result


def load_scanner(root: Path | None = None, explicit: str | None = None, allow_missing: bool = False) -> SecretScanner | None:
    try:
        home = resolve_home(root, explicit)
        return SecretScanner(load_patterns(home), home)
    except ScannerUnavailable:
        if allow_missing:
            print(
                "[warn] 未找到 skill-git 扫描器，已按 --allow-missing-scanner 跳过凭据扫描；"
                "这条记录不可直接推送到公开仓库。",
                file=sys.stderr,
            )
            return None
        raise
