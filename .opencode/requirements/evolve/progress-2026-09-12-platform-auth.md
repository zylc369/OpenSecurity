# 进度: platform-auth-and-attack-patterns（全部完成）

- [x] 步骤 1: platform-auth-strategy.md（REVISE 后 103 行: 决策树/执行模式选型/Turnstile/指纹基线/硬信号）
- [x] 步骤 1b: ~~noctf-platform.md~~ 已撤销（用户否决: 环境快照不是分析能力，删文件并清全部引用）
- [x] 步骤 2: web-analysis.md 小节 + 索引 2 行（platform-auth-strategy + noctf-platform）
- [x] 步骤 3: ssrf-advanced.md urljoin 小节（修正: 标准库声明，去版本叙事）
- [x] 步骤 4: file-upload.md 异常逃逸小节

返工记录（用户 REVIEW 指出）:
1. "（Python 3.12）"版本叙事 → 改为标准库声明 + Py3 全系一致说明
2. 指纹标题 macOS/Chrome 152 环境叙事 → 删除，改"诊断基线"定位
3. 硬编码 macOS Chrome 路径 + subprocess 启动 → channel="chrome" 通用方式;
   连接代码与 browser-debugging.md §2 重复 → 改为引用
4. noCTF 定制档案混在通用策略文档 → 拆分 noctf-platform.md
5. 决策树"headless + CDP"概念错误 → CDP 仅用于用户协助/会话保持场景（模式 B）
6. IIS6/7、Win2k3 术语不自包含 → 展开为自包含表述（3 处）

进化记录: security-analysis-evolve.md 规则 8.0「知识零来源叙事」铁律 + 规则 12.5 黑名单同步
