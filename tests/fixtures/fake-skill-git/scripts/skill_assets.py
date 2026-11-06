"""测试替身：模拟 skill-git 的凭据扫描器接口（只提供 SECRET_PATTERNS）。

真实环境请用 --skill-git-home 指向 skill-git 仓库；规则清单只有一份，
在 skill-git/scripts/skill_assets.py 里，本仓库不复制。
"""

import re

SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"FAKE_SECRET_[A-Za-z0-9]{6,}"),
)
