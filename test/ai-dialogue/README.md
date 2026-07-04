# ai-dialogue 测试

## 测试文件

| 文件 | 类型 | 依赖 | 说明 |
|------|------|------|------|
| `conftest.py` | 公共 fixture | 无 | 加载 ai-dialogue.py 模块；检测 opencode serve 可用性；定义测试常量 |
| `test_unit.py` | 单元测试 | 无网络 | 纯函数测试：URL 构造、响应解析、CLI 参数解析、错误处理（28 项） |
| `test_integration.py` | 集成测试 | opencode serve 运行中 | 真实 API 调用测试：创建/删除 session、发送消息、多轮上下文、chat 流程（10 项） |

## 运行方式

```bash
# 全部测试（单元 + 集成）
pytest test/ai-dialogue/ -v

# 仅单元测试（毫秒级，无需 serve）
pytest test/ai-dialogue/test_unit.py -v

# 仅集成测试（需要 opencode serve 运行中）
pytest test/ai-dialogue/test_integration.py -v
```

集成测试在 opencode serve 不可用时自动 skip。

## 单元测试覆盖

| 测试类 | 测试项 | 覆盖内容 |
|--------|:---:|---------|
| `TestBaseUrl` | 3 | `_base_url()` 不同 host/port 组合 |
| `TestParseSession` | 5 | 完整响应、缺 title、时间回退、无时间戳、空 model |
| `TestParseMessageResponse` | 6 | 标准、多段拼接、非文本过滤、空 parts、缺 info、空文本 |
| `TestBuildParser` | 11 | 各子命令必传参数校验、默认值、全参数、无子命令 |
| `TestRequestErrorHandling` | 2 | HTTP 错误（JSON body / 非 JSON body） |

## 集成测试覆盖

| 测试类 | 测试项 | 覆盖内容 |
|--------|:---:|---------|
| `TestSessionCreateDelete` | 4 | 创建返回 session_id、无 title 创建、删除返回 true、删除不存在的 session 报错 |
| `TestSessionList` | 2 | 列表返回 list、创建后包含该 session |
| `TestSendMessage` | 2 | 单轮回复内容、多轮上下文保持 |
| `TestChat` | 2 | 手动 create+send+delete 流程、_dispatch chat 路由 |
