"""工具 worker 子进程入口 —— `python -m src.orchestration_plane.l2.communication.tool_worker`。

由 tool_subprocess.run_tool_in_subprocess 启动，从 stdin 读 JSON 请求，
执行工具，向 stdout 写 JSON 响应。独立进程隔离，崩溃不拖垮主流程。
"""
from src.orchestration_plane.l2.communication.tool_subprocess import worker_main

if __name__ == "__main__":
    worker_main()
