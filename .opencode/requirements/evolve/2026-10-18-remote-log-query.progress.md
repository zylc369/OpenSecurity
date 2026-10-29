# 进度: 2026-10-18-remote-log-query

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. services/log_query.py | ✅ | 反向 chunk 读取核心；与 `grep\|tail` 基线逐字节一致 |
| 2. routes/logs.py + server.py 注册 | ✅ | 直调验证：正常/404/422 映射全对；pyright 0/0/0 |
| 3. routes/remote.py 转发端点 | ✅ | 双分支冒烟：local 真实查询 / remote 转 path+payload 全对 |
| 4. tests/test_logs_query.py | ✅ | 12 passed（反向读/跨块/长行/坏字节/校验矩阵/symlink） |
| 5. tests/test_remote_logs_forward.py | ✅ | 5 passed（local/转发/502/409/映射）；pyright 修复 2 处 memoryview |
| 6. 全量回归 + e2e | ✅ | 回归 266 passed / pyright 0/0/0；e2e 完成：两端日志查询全通 + 09:01 冷窗自查闭环（串行排队问题另立修复批 2026-10-18-relay-gateway-multiplex） |

## 证据

- 步骤 1: compile OK；pyright 全量 `0 errors, 0 warnings, 0 notes`；
  实测 `query_log(control.log, r"\[tts\]", 5)` 与 shell `grep -a | tail -5` 逐行一致；
  `limit=1 → more=True`（精确探测）；字面量 `[tts]` 命中 3；空 pattern 返回尾部 3 行。
- 步骤 2: 直调日志——正常返回 `LogQueryResult(file='t.log', lines=['[a]3'], more=False)`；
  404/422（非法正则/非法文件名）映射全 OK。
- 步骤 3: local 返回 `{"file":"node.log","lines":["[tts] warm start","[tts] done"],"more":false}`；
  remote 转发 `/api/logs/query` + payload `{'file': 'node.log', 'pattern': '\\[tts\\]', 'is_regex': True, 'limit': 10}`。
- 步骤 4/5: `pytest tests/test_logs_query.py tests/test_remote_logs_forward.py -q` → `17 passed in 0.19s`；
  pyright 全量 `0 errors, 0 warnings, 0 notes`。
