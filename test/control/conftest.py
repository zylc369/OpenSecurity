"""embed_client / control_url / 控制台后端共享 fixtures。

test_embed_client.py 和 test_control_backend.py 均为纯单元测试
（临时目录 + 环境变量隔离），不需要真实运行控制台。
"""
import sys
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers"
sys.path.insert(0, str(MCP_DIR))
