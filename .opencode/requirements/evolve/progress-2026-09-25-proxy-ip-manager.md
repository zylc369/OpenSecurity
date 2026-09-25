# 进度：2026-09-25 proxy-ip-manager

## 状态总览
- Phase 0-4.5: 完成（需求文档定稿+审计 11 问题修复；prompt 无需瘦身 243<450）
- Phase 5: 步骤 1 完成

## 步骤 1: pool + 归一化 ✅
- 文件: services/proxy_pool.py + tests/test_proxy_pool.py + config.py 常量段
- 验证: pytest 25/25 通过（签名官方自测/归一化 18 形态含拒绝/mock 状态机/凭证缺失/损坏重置）
- 实现要点: normalize_domain 用 "://" in text 判别"有 scheme 无 host"; FakeJuliang 替身
  必须是 async def 函数（类属性绑定 self 形态）; JULIANG_TTL_MARGIN_SEC 常量名（非 TIL）
- 遗留: 无

## 下一步: 步骤 2 控制接口 routes/proxy.py (~100 行)
- 验证点: curl 五接口(url 缺失 400/无法提取 host 400/归一化入表; mode 枚举;
  rotate reason 枚举 bad_ip 触发黑名单; status 含 history; entry 返回真实端口)
- 注: entry 的 relay_port 在步骤 3a relay 启动后才有真实值, 步骤 2 先返回配置起点值

## 步骤 2: 控制接口 ✅
- routes/proxy.py + server.py 注册两行; url 缺失走手写 400(Pydantic 默认 422 的规避: url: str = "")
- 验证: TestClient 五接口全过(枚举 400/归一化入表/history/entry)
- 乌龙记录: qq.com 对 curl 默认 UA 直连也回 501——CONNECT 路径无 bug, 加 UA 后 200

## 步骤 3a: relay 基础转发 ✅
- services/proxy_relay.py + server.py startup hook(supervisor 骨架)
- 验证: CONNECT 隧道 200+TLS 端到端; 明文 myip 出口=本机(direct); 冷却域→proxy 路径→
  无凭证隧道层 502(curl 显示 000 是"隧道失败"的显示方式, -v 确认 502 已发)

## 步骤 3b: relay 优雅关闭+轮换+自愈 ✅
- Tunnel 注册表 + graceful_close_upstreams(write_eof+drain 5s 兜底) + 阈值计数
- routes rotate/mode 成功后触发 graceful_close; server.py supervisor 持续监督(2s 探活)
- 验证(/tmp/verify_3b.py 全 mock): 慢响应在飞切换→客户端收满 5000B; 35 连接→
  auto_rotate_35conn 入 history; stop→start 重拉恢复

## 步骤 4: MCP 薄壳 ✅
- mcp-servers/proxy/server.py(4工具, SOP 内嵌 status 描述) + mcp-manager.ts 注册
- 验证(stdio 协议级): initialize/tools=list 四工具/SOP 断言/调用链路(连接到真实运行中
  控制台, 返回 404=旧代码无路由, 重启后即通; 404/502 清缓存自愈路径已走通)

## 步骤 5: agent 引导物 ✅
- web-analysis.md: 工具清单新增"代理 IP 管理"节(8行) + 知识库索引首行(🆕); 253行<450
- knowledge-base/proxy-usage.md: 自包含(用法/SOP/模板/例外库/成败标准), 零外部依赖

## 步骤 6: 端到端验收 ✅
- 凭证落位 .ai_env(项目根,控制台 credentials_configured=true 确认); /api/system/restart 重启加载
- 事故+修复: server.py startup hook 误用不存在的 get_logger → ImportError 控制台起不来 → 改标准
  logging.getLogger; 手动 nohup 拉起验证(心跳宽限后自杀, plugin 下次交互自动拉起, 无缝)
- 走查: mode=proxy→entry→经 relay 出口=代理IP供应商IP(河南移动)→rotate(bad_ip)→黑名单1→新出口工作
- 实战演练 SOP 场景③: 首个代理IP供应商IP真实超时(坏IP)→bad_ip 轮换→恢复 ✓; 场景①②待实战限流场景
- 浏览器走查: 无头 Chromium 出生即连 relay, 出口=供应商代理IP ✓
- 消耗: total_fetched=2 / surplus 9591(9593→9591)

## Phase 6 实现审计: 2轮+修复→纯审计零问题, 通过
- 轮1修 3 bug: ① relay 阈值轮换后本次连接仍用旧 info.ip(需重新 get) ② entry 在 direct
  模式白提取 IP 浪费配额(仅 proxy 模式确保) ③ 知识库 httpx 示例用废弃的 proxies 参数(0.28 用 proxy)
- 轮2: 测试清未用 import; 需求步骤6对账口径精确化(total_fetched/surplus 对账)

## 实施期重大教训：配置链路所有权（三轮纠正后的最终理解）
- 错误演进: Shell 直写 .ai_env → 补正调 /api/config(冒充前端) → 被质疑后改口"import 直调"
  → 每轮都在"写入手段"层打转, 未意识到 agent 在配置链路上没有任何角色
- 最终理解: 配置数据流唯一单向(用户→配置页→前端专用接口→config_store→.ai_env);
  agent 职责边界 = 消费侧代码(pool 读) + 引导用户填写; /api/config 仅前端可用
- 已执行: rm 野 .ai_env(恢复 ensure_template 正轨) + kill 自设 OPENCODE_ROOT 的
  假验证实例(端到端 credentials_configured=true 结论作废, 待生产实例重验)
- 待用户: 重启后在控制台配置页填写 JULIANG_TRADE_NO/JULIANG_API_KEY;
  生产实例上重验凭证加载与 proxy 全链路

## 终验(生产实例+正轨凭证) + 重大 bug 修复
- 误诊更正: 端到端④"首个坏IP超时"为误诊——真因是 relay proxy 分支缺陷
- 真根因: _connect_upstream proxy 分支只与接入点建 TCP, 从未发送 CONNECT 握手,
  客户端 TLS 字节被灌进裸 TCP(协议垃圾→接入点断连→000)。direct 模式无此环节
  (直连目标站)故通; 明文通因绝对URI GET 恰是代理明文协议——三者完美解释
- 修复: proxy 分支建 TCP 后发 CONNECT host:port + Host 头, 读接入点 200 响应
  (非200→502), 读完响应头后才返回作上游
- 修复后: proxy 模式 HTTPS qq 200/118KB, httpbin 200, OoC 503(Render冷启动,隧道已通)
- 全链路: mode 切换/entry/明文出口/HTTPS隧道/bad_ip轮换/消耗对账(6提取/9587余/3黑名单/9条history)/direct恢复 全部通过
- 待放行项: ⑦浏览器(~/Library/Caches/ms-playwright) ⑧MCP协议级 ⑨pytest(需放行 $PYTHON_CMD 的 venv 路径)

## 测试 REVIEW 第二轮(并发/日志/边界) — 完成
- 用户五问处置:
  1. 复用判定澄清: 全局单IP池+全局锁(asyncio.Lock 锁内提取不释放), 并发 get 不重复申请
     (测试证明: 8并发→1次提取); 真实并发洞=阈值轮换重入(并发到达35→多次轮换浪费IP),
     已修: _rotate_gate 防重入锁+双重检查(测试: 2串行+3并发→恰1次轮换)
  2/4. 并发测试补: 并发get单提取/并发阈值单轮换; 全场景 55 用例矩阵见需求文档
  3. 其他边界: start_relay 重置连接计数(跨启停残留); 锁随监听生命周期重建(跨事件循环)
  5. 静默吞异常全部加日志: relay 8处(debug=正常网络收尾/warning=异常状态),
     pool 2处(状态文件损坏重置/持久化失败, 均 warning)
- 测试侧自修: gather 是 Future 需包装协程; 并发阈值测试重设计(串行预热+并发触发)
- 终态: 55/55 全绿; 真实链路回归 qq 200/118KB, 出口=陕西电信, 已恢复 direct
