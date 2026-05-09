# -*- coding: utf-8 -*-
"""
Pytest 引导文件（测试运行环境修复）
================================

问题背景
-------
本仓库采用“直接以仓库根目录作为源码根”的布局（例如 `observatory/`, `state_pool/` 等都是顶层包）。
在某些运行方式下（尤其是直接执行 `pytest ...` 且工作目录/导入路径不稳定时），pytest 可能无法
自动把仓库根目录加入 `sys.path`，从而出现：

  ModuleNotFoundError: No module named 'observatory'

这会直接影响“找茬式验收/回归测试”的效率。

解决方式
-------
在 pytest 启动时把仓库根目录注入到 sys.path 的最前面，保证：
  - `import observatory`
  - `import state_pool`
  - `import innate_script`
等导入在测试环境下稳定可用。

说明
----
此文件仅影响测试运行，不影响生产运行。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_root_on_syspath() -> None:
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_ensure_repo_root_on_syspath()

