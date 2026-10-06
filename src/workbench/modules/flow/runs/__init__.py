"""运行历史 —— 归属「验证管理系统」业务线。

左窗格里的那棵树。刻意让「正在跑的」和「跑完的」是同一类条目：
判据是 `docs/run_events.jsonl`（跑着就有）而不是 `docs/manifest.json`
（跑完才写）—— 否则打开界面最想问的那个问题（"这次跑到哪了"）根本没得答。
"""
from .module import RunsModule

__all__ = ["RunsModule"]
