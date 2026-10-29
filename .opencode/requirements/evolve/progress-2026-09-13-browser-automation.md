# 进度: browser-automation-consolidation（全部完成）

- [x] 步骤 1: browser_cdp.py 新增（217 行, 纯标准库）
  - 语法/--help/probe JSON ✓; start 复用分支(9222) ✓; start 完整链(9223→system 级 Chrome Beta) ✓
  - 脱离进程存活 ✓; curl 交叉验证 ✓; kill+profile 清理 ✓
  - 函数级验证: playwright-cache 分支命中 chromium-1223, 优先级 system > playwright-cache ✓
- [x] 步骤 2: browser-automation.md 新建（282 行, Write+Edit 分两次）
  - 覆盖对照: 旧两文档 10 章节全有去处（"自动 resume 断点"漏迁移已补齐）
  - Popen 错误示例修正为引用 §1.3; 重复语句合并; 新增 §1.1-1.3/§7.5-7.6/§8 齐全; 零叙事词
- [x] 步骤 3: 消费方引用更新 + 旧文件删除
  - web-analysis.md L105 改引用+铁律行, L168/169 索引合并; client-side-attacks.md L212 更新
  - 两个旧文件已删; 全库 grep 旧文件名零残留（requirements 归档除外）
- [x] 步骤 4: deserialization.md §4 增补（148 行总计, 新增 ~30 行）
  - 8 知识点在场 ✓; 零叙事词 ✓; 与既有 STOP 剥离链互补关系注明 ✓
- [x] 步骤 5: web-analysis.md 铁律行 + 瘦身检查
  - 铁律行含 $AGENT_DIR/scripts/browser_cdp.py ✓; 展开 397 行 < 450 ✓

Phase 6 审计:
- 第 1 轮: P1 Playwright 缓存分支未实测→函数级验证 PASS; P2 验收8全库启动实现残留→grep 仅权威处自身; P3 §1.1 headed 边界不明→已补; P4 I46\n 表格歧义→改 "I46"+LF
- 第 2 轮 + 纯审计轮: 零问题
- 规则 12 自检 7 条全过

用户 REVIEW 返工（第 2 次）:
1. prompt 表述弱化铁律（"浏览器自动化优先"与铁律并列）→ 重写为"按场景分流（互斥）"结构,
   铁律分支用"必须/禁止"; 顺带修正 "headless Chrome + CDP" 概念残留（headless 自动化不需要 CDP）
2. browser_cdp.py 异常路径未测 → 补全套 6 项测试全 PASS:
   T1 非执行文件 exit3+优雅报错 / T2 假chrome即退 exit3+stderr回显 / T3 挂起 exit4+诊断(17s)
   T4 探测链全空 exit2 / T5 probe false JSON / T6 --url 页面真实打开
3. 测试发现真 bug: Popen 未 catch OSError（裸 traceback）→ 已修, 沉淀回归测试
   web-analysis/scripts/test_browser_cdp.py（路径改脚本相对, 沉淀版 6/6 PASS）
4. 展开 399 行 < 450 ✓; 测试残留 profile 清理 ✓

用户 REVIEW 返工（第 3 次）: 表述限窄+两节冲突 → 第 4 次返工整体重写（见下），本轮作废

用户 REVIEW 返工（第 4 次）:
1. 根因修正: "凡是有界面浏览器（任何目的）"把形态当决策输入（错误）——任务需求才是输入;
   且决策树 Default "headless 优先"与铁律"有界面走 browser_cdp.py"各说各话
   （登录时用户想看着，Default 却给了看不见的 headless）
2. 心智模型修正: 网页操作默认 = 可见的独立 Chrome（用户可观察可介入）; headless 才是例外
   （纯后台批量任务专用）
3. 重写范围: §1.1 铁律（任务需求出发: 交互操作→browser_cdp.py, 纯后台→headless launch）
   / §1.4 模式对比（选型一句话: 交互一律 B, 纯后台用 A）/ §2 决策树
   （Default 改为 browser_cdp.py+接管自动填表, 全程可见）/ prompt 分流行同步
4. 一致性: 旧表述零残留; 展开 397 < 450

代码审计（独立审计流程, 截至周期2R2 修复 6 处）:
- 周期1R1 修复 3: §3 人机验证表 channel="chrome" 模式A语言残留→改为指向 §2 Default+纯后台场景;
  start JSON 补 profile 字段（docstring/reuse分支/§1.2/测试四处同步, T6 改精确清理）;
  2 处 open().read() 未 close → with open
- 周期1R2 修复 1: reuse 分支 JSON 变更补实测（9222 真实实例, 四字段完整验证）
- 周期2R1 修复 1: import tempfile 死代码删除（stderr 落盘方案变更遗留）
- 周期2R2 修复 1: 进度文档补记本审计节（本条）
- 回归: test_browser_cdp.py 7/7 PASS; probe 复测正常; ast 死 import 扫描零真阳性
- 周期3 两轮零问题, 审计通过（累计 7 问题全修复; Windows 分支静态审查, 首次使用需实测）

用户 REVIEW 返工（第 5 次）:
1. prompt"平台登录策略"小节与 browser-automation.md 高度重复（铁律/决策树/5轮上限/sitekey 密钥值均为复述）
   → prompt 压缩为 3 行: 行动指令+防错关键+独有求助规则（凭证直接问/手段非目的）; 复述全删;
   独有知识"凭证猜测连败 3 次"并入 §4 硬信号后再删 prompt 版; 展开 397→394
2. 引用句"启动用法、登录决策树...见 X"罗列内容目录缺触发条件 → 改"执行浏览器操作前先读 X"+章节号定位
3. .browser-profiles 测试残留清理 + gitignore（追加时拼接 bug 修复, check-ignore 验证生效）;
   test T6 kill 后补 sleep 1.5 再删 profile（句柄释放）; 最终展开 395 < 450
