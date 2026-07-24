# Events MCP entity_types 定义 + node_labels 描述收口

## §1 背景与目标

### 1.1 来源

events MCP 工具简化（8→6）后发现 node_labels 从未正常工作：`write_event_daemon.py` 调用 `graphiti.add_episode()` 时未传 `entity_types`，导致 graphiti 提取的实体全部标记为 `Entity`，`node_labels=["Tool"]` 等过滤永远返回空。

### 1.2 问题

| # | 问题 | 位置 |
|---|------|------|
| 1 | `add_episode()` 未传 entity_types → 所有实体标签为 Entity | write_event_daemon.py:57 |
| 2 | entity_search/entity_relationships_search 的 node_labels 描述随手编写，不是基于实际标签 | server.py |
| 3 | 两个工具的 node_labels 描述不一致 | server.py |

### 1.3 目标

1. 定义安全分析专用的 entity_types（8 种 + Entity 兜底）
2. 写入时传 entity_types 给 graphiti.add_episode()
3. node_labels 描述收口为统一常量

## §2 技术方案

### 2.1 entity_types 定义

```python
class ToolEntity(BaseModel):
    """A software tool or utility (e.g., nmap, frida, IDA Pro, sqlmap, Ghidra)."""

class HostEntity(BaseModel):
    """A network host, server, or device (e.g., 192.168.1.1, server.example.com)."""

class VulnerabilityEntity(BaseModel):
    """A security vulnerability, CVE, or weakness (e.g., CVE-2024-1234, buffer overflow)."""

class FileEntity(BaseModel):
    """A file, binary, or artifact (e.g., target.exe, config.yaml, app.apk)."""

class EndpointEntity(BaseModel):
    """A web endpoint, URL, or API route (e.g., /api/login, /actuator/env)."""

class AlgorithmEntity(BaseModel):
    """A cryptographic algorithm or math construct (e.g., RSA, AES, ECDLP, LLL)."""

class ModelEntity(BaseModel):
    """An AI/LLM model being tested (e.g., GPT-4, Claude, Llama-3)."""

class PromptEntity(BaseModel):
    """A prompt, system instruction, or injection payload for AI systems."""

CUSTOM_ENTITY_TYPES = {
    "Tool": ToolEntity,
    "Host": HostEntity,
    "Vulnerability": VulnerabilityEntity,
    "File": FileEntity,
    "Endpoint": EndpointEntity,
    "Algorithm": AlgorithmEntity,
    "Model": ModelEntity,
    "Prompt": PromptEntity,
}
```

graphiti 的 `_build_entity_types_context` 会在这些基础上加 `{id:0, name:"Entity"}`（兜底）。

### 2.2 写入路径改动

`write_event_daemon.py` 的 `graphiti.add_episode()` 调用加 `entity_types=CUSTOM_ENTITY_TYPES`。

### 2.3 node_labels 描述收口

```python
NODE_LABELS_DESCRIPTION = (
    "实体类型过滤，可选值："
    "Tool（工具）、Host（主机）、Vulnerability（漏洞/CVE）、"
    "File（文件/二进制）、Endpoint（Web 端点）、"
    "Algorithm（加密算法）、Model（AI 模型）、Prompt（提示词）。"
    "不传则搜全部类型。"
)
```

`entity_search` 和 `entity_relationships_search` 的 `node_labels` 参数引用此常量。

## §3 实现规范

### 3.1 改动范围表

| 文件 | 改动 | 行数 |
|------|------|------|
| `mcp-servers/events/graphiti_config.py` | 新增 CUSTOM_ENTITY_TYPES | ~30 |
| `mcp-servers/events/write_event_daemon.py` | add_episode 传 entity_types | ~5 |
| `mcp-servers/events/server.py` | NODE_LABELS_DESCRIPTION 常量 + 描述引用 | ~15 |
| `agents/memorist.md` | node_labels 说明更新 | ~5 |

### 3.2 实施步骤

#### Step 1. graphiti_config.py 定义 entity_types

- 新增 8 个 BaseModel 子类 + CUSTOM_ENTITY_TYPES dict
- 文件顶部加 `from pydantic import BaseModel`
- **验证点**: python 语法通过
- **依赖**: 无

#### Step 2. write_event_daemon.py 传 entity_types

- import CUSTOM_ENTITY_TYPES
- add_episode() 调用加 `entity_types=CUSTOM_ENTITY_TYPES`
- **验证点**: python 语法通过
- **依赖**: Step 1

#### Step 3. server.py node_labels 描述收口

- 定义 NODE_LABELS_DESCRIPTION 常量
- entity_search 的 node_labels Field 引用常量
- entity_relationships_search 的 node_labels Field 引用常量
- **验证点**: python 语法通过 + grep 确认两处引用一致
- **依赖**: 无

#### Step 4. memorist.md node_labels 说明更新

- 更新 node_labels 说明段，列出实际可选标签
- **验证点**: 人工读一遍
- **依赖**: Step 3

## §4 验收标准

| ID | 验收项 |
|----|--------|
| F1 | CUSTOM_ENTITY_TYPES 包含 8 种类型 |
| F2 | write_event_daemon.py add_episode 传 entity_types |
| F3 | entity_search 和 entity_relationships_search 的 node_labels 描述一致 |
| F4 | memorist.md 列出实际可选标签 |
