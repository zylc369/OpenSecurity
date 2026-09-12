# 平台登录策略 + 攻击模式沉淀（platform-auth & attack patterns）

> 来源: 2026-09-12 Web 平台登录绕路复盘。
> 用户确认执行项 ①②③④，明确不做 ⑤（browser_session.py 通用脚本）。

---

## §1 背景与目标

**来源痛点**（该次任务数据）:

| 环节 | 调用数 | 有效率 | 问题 |
|------|-------|--------|------|
| 源码分析 + 本地验证 | ~15 | 100% | 无 |
| 平台登录（API 逆向路线） | ~20 | ~25% | 猜 email 20+ 次全败 → 转注册撞 CAPTCHA → 挖 header 机制；被用户纠偏 2 次仍二次犯错 |
| 浏览器接管 + 完成利用 | ~8 | 100% | 无 |

**根因链**（复盘确认）: 表面是"被 CAPTCHA 挡"，实际是登录端点本无 CAPTCHA、CAPTCHA 只挡自选的注册绕路；根本原因是把登录（手段）当成了技术挑战（目的），未做成本核算，且默认路径选了 API 逆向而非浏览器自动化。

**三轮对比实验**（用户协助完成）:
- 纯 API 路线: 失败（不知道 email；注册撞 CAPTCHA）
- headed Chrome + CDP 自动登录: 成功，21 秒，Turnstile 未触发
- headless Chrome（--headless=new）+ CDP 自动登录: 成功，15 秒，UA 带 HeadlessChrome 标记仍未被拦

**目标**:
1. 登录类场景的调用浪费从 20+ 降到 ≤4（-80%）
2. 行为层兜底: 硬信号出现时立即升级求助，消除二次犯错
3. 沉淀两个已实战验证的攻击原语（urljoin 可控 base、异常逃逸保留文件），下次直取

---

## §2 技术方案

### ① 新建 `$AGENT_DIR/knowledge-base/platform-auth-strategy.md`（~45 行，纯增量: 决策/判别/密钥知识）

```
1. 登录决策树（Default 自动登录 → 升级1 验证组件点击 → 升级2 用户协助接管;
   定位: API 逆向不作为完成登录的手段，禁逆向前端超 5 轮）
2. 执行模式选型（A: launch(channel="chrome") 自动登录默认;
   B: 独立进程+CDP 接管——用户协助/登录态跨脚本; 代码引用 browser-debugging.md §2）
3. 人机验证两类机制判别（环境评分 vs 服务端 CAPTCHA 路由）+
   配置端点查法 + 无头行为结论（HeadlessChrome UA 不构成拦截依据）
4. 硬信号（Turnstile 测试密钥族三值 / CAPTCHA failed validation）
```

> 返工记录: 初版 103 行混入 AI 本会写的执行细节（fill/click/检测代码/指纹表）
> 和与 prompt 重复的原则（凭证直接问/成本核算/二次犯错），用户 REVIEW 后
> 两轮瘦身——只留 AI 默认不会的真增量。

### ② 修改 `$OPENCODE_ROOT/agents/web-analysis.md`（+9 行）

- 在「Web 安全分析核心原则」小节后新增「平台登录策略」小节（~8 行）:
  登录需求 → 浏览器自动化优先（headless+CDP，详见知识库文档）; 硬信号 → 停止重试升级求助; 凭证直接问禁止猜 3 次以上; 登录是手段，绕过成本 > 询问成本必须升级
- 「知识库索引」表新增 `platform-auth-strategy.md` 一行（触发条件: 需要登录任何 Web 站点/平台才能继续时）

### ③ 修改 `$AGENT_DIR/knowledge-base/ssrf-advanced.md`（§3 增补 ~15 行）

新增小节「urljoin 可控 base（Python）」:
- 触发场景: `fetch(urljoin(base, resource))` 且 base 来自用户输入（session/参数）
- 三性质（Python 3.12 行为值）:
  1. 绝对 URL 直接替换: `urljoin("https://x/api/", "file:///a/b")` → `file:///a/b`
  2. 同名段自反: `urljoin("file:///a/b/permissions", "permissions")` → 读回自身
  3. 去尾拼接: `urljoin("file:///tmp/users/x", "user/settings")` → `file:///tmp/users/user/settings`（dirname(base.path) + relative）
- 落点计算法: resource 相对路径的每一段都会落到 dirname(base) 之下——反推可控写入路径与读取点对齐
- 负知识: `data:` 不在 Python uses_relative，urljoin 丢弃 base 返回 relative 原文 → urlopen 报 unknown url type
- 前提: urlopen 默认装 FileHandler（file:// 可读）

### ④ 修改 `$AGENT_DIR/knowledge-base/file-upload.md`（§9 增补 ~12 行）

§9「竞争条件上传」后新增「异常逃逸保留文件（免竞态）」:
- 触发场景: 上传文件处理后有清理逻辑（os.remove），清理在 try/except 内且 except 只捕获窄子类
- 原理: 逃逸异常 → 500 → 清理不执行 → 同批已写入文件永久化
- 逃逸面: `json.loads` 只捕获 `json.JSONDecodeError` 时，UnicodeDecodeError（ValueError 同父类）逃逸; 深嵌套 JSON 触发 RecursionError 逃逸
- 构造细节: 内容 `b'\xff'` → UnicodeDecodeError; **必须奇数字节**——`b'\xff\xfe'` 被识别为 UTF-16-LE BOM，decode 成功后走 JSONDecodeError 被捕获
- 审计特征: 源码 grep `except json.JSONDecodeError`、`except ValidationError` 等窄类型 + 邻近 os.remove

---

## §3 实现规范

### 改动范围表

| # | 文件 | 操作 | 行数 |
|---|------|------|------|
| ① | `$AGENT_DIR/knowledge-base/platform-auth-strategy.md` | 新建 | ~130 |
| ② | `$OPENCODE_ROOT/agents/web-analysis.md` | Edit ×2（新增小节 + 索引行） | +9 |
| ③ | `$AGENT_DIR/knowledge-base/ssrf-advanced.md` | Edit ×1（§3 后插入） | +15 |
| ④ | `$AGENT_DIR/knowledge-base/file-upload.md` | Edit ×1（§9 后插入） | +12 |

### 编码规则

- 知识内容遵守 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`: 写"什么场景、怎么检查、怎么利用"，不写经验来源/赛事名/时间线叙事
- 引用路径用 `$AGENT_DIR`/`$SHARED_DIR` 变量，禁止绝对路径
- 技术断言写入前必须在本机验证（urljoin 三性质、\xff 行为、CDP 指纹），禁止无依据泛化
- 跨文档不重复: urljoin 细节只在 ssrf-advanced.md，platform-auth-strategy.md 只引用; noCTF 档案只在 platform-auth-strategy.md

### §3.1 实施步骤拆分

```
步骤 1. 新建 platform-auth-strategy.md
  - 文件: $AGENT_DIR/knowledge-base/platform-auth-strategy.md（Write 一次性创建，<300 行合规）
  - 预估行数: ~130
  - 验证点: 人工通读——① 五个章节齐全且自包含（不依赖主 prompt 上下文可理解）
           ② 所有引用用 $AGENT_DIR 变量 ③ 无经验来源/时间线叙事
           ④ 决策树三层路径 + 定位声明完整
  - 依赖: 无

步骤 2. web-analysis.md 加「平台登录策略」小节 + 索引行
  - 文件: $OPENCODE_ROOT/agents/web-analysis.md（Edit ×2: 核心原则后插小节; 知识库索引表加行）
  - 预估行数: +9（小节 8 行 + 索引 1 行）
  - 验证点: ① 小节含硬信号清单与"浏览器优先"规则 ② 索引行触发条件明确
           ③ 展开行数计算: 229 - 7(占位符行) + 7片段实际行数 + 9 < 450
           ④ 其余内容零改动（diff 确认只有两处新增）
  - 依赖: 步骤 1（小节引用该文档）

步骤 3. ssrf-advanced.md 增补 urljoin 小节
  - 文件: $AGENT_DIR/knowledge-base/ssrf-advanced.md（Edit ×1: §3 URL 解析器差异表格后插入）
  - 预估行数: +15
  - 验证点: ① 本机复跑三性质断言（python -c urljoin）与文档值一致
           ② 与 §3 现有内容不重复（现有是过滤器差异，新增是 fetch base 可控）
  - 依赖: 无

步骤 4. file-upload.md 增补异常逃逸小节
  - 文件: $AGENT_DIR/knowledge-base/file-upload.md（Edit ×1: §9 竞争条件上传后插入）
  - 预估行数: +12
  - 验证点: ① 本机复跑 json.loads(b'\xff') 与 json.loads(b'\xff\xfe') 验证奇偶字节断言
           ② 与 §9 竞态内容互补不重复（竞态=时间窗，异常逃逸=控制流绕过）
  - 依赖: 无
```

---

## §4 验收标准

### 功能验收

- [ ] platform-auth-strategy.md 存在且五章节齐全，决策树三层路径 + 定位声明完整
- [ ] web-analysis.md 新小节 + 索引行生效，grep 可检到 `platform-auth-strategy`
- [ ] ssrf-advanced.md 含 urljoin 三性质 + data: 负知识 + 落点计算法
- [ ] file-upload.md 含异常逃逸（\xff 奇数字节约束 + 逃逸面枚举 + 审计特征）

### 回归验收

- [ ] web-analysis.md 除两处新增外零改动（git diff 验证）
- [ ] ssrf-advanced.md / file-upload.md 原有小节内容零改动
- [ ] urljoin 行为值、json.loads 行为断言在本机复跑通过

### 架构验收

- [ ] 新文档位于 web-analysis/knowledge-base/（登录策略为 Web 分析场景专属）
- [ ] 无循环引用、无绝对路径、无 docs/ 引用
- [ ] 依赖方向合规（纯知识库 + prompt 改动，不涉及代码层）

---

## §5 与现有需求文档的关系

- 与 `progress-2026-09-05-evolve.md` 等历史进度文档无交集（本次全部为 web-analysis 域新增/增补）
- 方案 ⑤（browser_session.py）用户明确不做，本文档不含该项; 若未来登录场景手写脚本模式再现 ≥3 次，可重新评估
