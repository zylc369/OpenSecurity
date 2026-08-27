# 贡献指南

> **中文** | [English](CONTRIBUTING.en.md)

感谢你对 OpenSecurity 的兴趣！这个平台的核心价值在于**社区共建的知识库与工具链**——每个安全研究员的实战经验，都可以沉淀成可复用的脚本或文档，让平台越用越强。

## 欢迎的贡献类型

| 类型 | 难度 | 例子 |
|------|------|------|
| 🐛 Bug 修复 | 低 | 修复脚本崩溃、prompt 逻辑错误 |
| 📚 文档改进 | 低 | 修正描述、补充示例、翻译 |
| 🔧 知识库补充 | 中 | 新增漏洞模式、壳处理策略、算法识别技巧 |
| 🛠️ 工具脚本 | 中 | 新增 IDAPython 脚本、Frida Hook 模板 |
| 🤖 新 Agent | 高 | 扩展新的安全分析领域（详见[添加新 Agent 指南](docs/contributing/add-new-agent.md)） |
| 🎯 平台机制 | 高 | Plugin hook 增强、上下文管理优化 |

## 行为准则

- **友好尊重**：技术讨论对事不对人，不人身攻击
- **耐心清晰**：对新贡献者友好，提问前先搜索现有 issue
- **事实优先**：技术结论需要可验证的证据（IDA 输出、工具结果、源码引用），不凭感觉下结论
- **安全红线**：不在 PR 中提交针对未公开漏洞（CVE 未公开期内）的真实漏洞利用细节，不提交可被直接滥用的攻击工具

## 开发环境搭建

```bash
# 1. Fork 仓库后克隆
git clone https://github.com/<your-username>/OpenSecurity.git
cd OpenSecurity

# 2. 添加上游
git remote add upstream https://github.com/zylc369/OpenSecurity.git

# 3. 安装开发依赖（OpenCode Plugin SDK + 测试工具）
cd .opencode && bun install && cd ..
python -m pip install pytest

# 4. 链接到工作目录测试
ln -s "$(pwd)/.opencode" ~/your-workspace/.opencode

# 5. 验证 Plugin 加载
# 启动 opencode，进入任一 Agent 会话，确认 system prompt 顶部出现
# [系统完整性] Plugin 已加载。当前 Agent: ...
```

详见 [README 快速上手](README.md#快速上手)。

## 贡献流程

### 1. 找任务

- 浏览带 [`good first issue`](https://github.com/zylc369/OpenSecurity/labels/good%20first%20issue) 标签的 issue（适合首次贡献）
- 浏览带 [`help wanted`](https://github.com/zylc369/OpenSecurity/labels/help%20wanted) 标签的 issue
- 阅读 [Roadmap](docs/ROADMAP.md) 找感兴趣的方向
- 自己发现 bug 或改进点也可以直接提 issue

### 2. 开发

```bash
# 从 main 创建分支（命名规范见下文）
git checkout -b feat/add-rust-analysis-agent
# 或
git checkout -b fix/query-py-thunk-crash

# 开发...开发...开发...

# 本地测试
cd test && python -m pytest test_opencode.py
```

### 3. 提交

```bash
git add <相关文件>
git commit -m "<type>: <简要描述>"
```

#### Commit Message 规范

格式：`<type>: <描述>`

| type | 用途 | 例子 |
|------|------|------|
| `feat` | 新功能 | `feat: 新增 Rust 二进制分析 Agent` |
| `fix` | Bug 修复 | `fix: query.py thunk 追踪时崩溃` |
| `docs` | 文档 | `docs: 补充 Frida 17.x 迁移指南` |
| `refactor` | 重构（无功能变化） | `refactor: 抽取 _base.py 的 JSON 输出逻辑` |
| `perf` | 性能优化 | `perf: initial_analysis.py 并行化字符串扫描` |
| `test` | 测试 | `test: 新增 update.py rename 单元测试` |
| `chore` | 杂项 | `chore: 升级 @opencode-ai/plugin 到 1.5.0` |

#### 分支命名规范

- 功能：`feat/<简短描述>`，如 `feat/rust-agent`
- 修复：`fix/<简短描述>`，如 `fix/thunk-crash`
- 文档：`docs/<简短描述>`，如 `docs/ipa-tutorial`

### 4. 提 PR

```bash
git push origin feat/add-rust-analysis-agent
# 在 GitHub 上发起 PR，目标分支 main
```

PR 模板会引导你填写：
- 改了什么、为什么改
- 如何测试
- 是否影响现有功能

## 代码规范

### Python（工具脚本）

继承 `binary-analysis/` 的 IDAPython 编码规范：

- 使用 `from _base import run_headless, log, ...` 导入公共模块
- headless 入口在模块级执行（不在 `if __name__` 内）
- **禁止** `import idc`、`import idaapi`、`from ida_xxx import yyy`（统一走 `_base` 封装）
- 字符串使用双引号
- 日志使用中文，包含 `[*]`/`[+]`/`[!]` 前缀
- 必须调用 `auto_wait()` 和 `qexit()`（由 `run_headless` 自动处理）

完整规范见 [`.opencode/binary-analysis/knowledge-base/idapython-conventions.md`](.opencode/binary-analysis/knowledge-base/idapython-conventions.md)。

### TypeScript（Plugin）

- 严格类型（避免 `any`，必要时显式标注）
- 错误处理：所有外部调用（fs、execSync、API）必须有 try-catch
- 日志：使用 `debugLog()`，不要直接 `console.log`
- 文件路径：使用 `join()` 而非字符串拼接

### Markdown（Agent prompt / 知识库）

- 中文为主（与现有文档一致）
- 使用 `{{buwai-rule:片段名}}` 引用共享片段，避免重复
- 表格优于长段落
- 命令示例必须可复制粘贴执行（路径用变量或绝对路径）
- 知识库文档遵循"按需加载"原则：单个文件聚焦一个主题，不堆砌

### Agent prompt（`.opencode/agents/*.md`）

修改 Agent prompt 时注意：
- frontmatter 字段必须完整（`description`、`mode`、`buwai-extension-id`、`permission`）
- 修改共享规则用 `agents-rules/`，修改 Agent 专属逻辑改 `.md` 本身
- 任何修改都要实测一次完整分析流程，确保不破坏现有行为

## 项目结构速查（贡献时去哪里改）

| 改什么 | 改哪里 |
|--------|--------|
| Agent 的工作逻辑 | `.opencode/agents/<name>.md` |
| 跨 Agent 的共享规则 | `.opencode/agents-rules/<rule>.md` |
| Plugin 行为（hook、注入逻辑） | `.opencode/plugins/security-analysis.ts` |
| 二进制工具脚本 | `.opencode/binary-analysis/`（含 `_base.py` 等基础层） |
| 移动端工具/知识库 | `.opencode/mobile-analysis/` |
| Web 工具/知识库 | `.opencode/web-analysis/` |
| AI 安全工具/知识库 | `.opencode/ai-security-analysis/` |
| 用户文档 | `docs/` |
| 测试 | `test/` |

## 新增工具脚本的流程

1. **判断归属**：是 IDAPython 脚本（走 idat）还是纯 Python 脚本（独立运行）？
2. **复用基础层**：从 `_base.py` 导入 `run_headless`、`log`、`JSONEncoder` 等
3. **环境变量传参**：不要用 `sys.argv`，统一用 `IDA_*` 环境变量（参考 `query.py`）
4. **JSON 输出**：所有结果写到 `IDA_OUTPUT` 指定的路径，不要打印到 stdout
5. **文档化**：脚本头部 docstring 写清用途/参数/示例调用，并在对应 Agent 的知识库中沉淀调用模板
6. **测试**：用一个真实样本跑通完整流程

## 新增知识库文档的流程

1. **判断主题边界**：单个文档聚焦一个主题（如"VMProtect 处理策略"），不要做大杂烩
2. **选择目录**：放对应 Agent 的 `knowledge-base/` 下
3. **格式**：参考现有文档（标题层级、表格、命令示例）
4. **触发条件**：在 Agent 主 prompt 的"知识库索引"表格中登记触发条件
5. **按需加载**：不要在 Agent 启动时强制加载，让 Agent 根据场景判断

## PR Review 标准

Reviewer 会检查：

- [ ] 代码符合上述规范
- [ ] 新增功能有对应的文档或 prompt 更新
- [ ] 不破坏现有 Agent 的工作流程（关键：实测一次）
- [ ] commit message 符合规范
- [ ] 没有提交 `~/bw-security-analysis/` 下的运行时数据
- [ ] 没有提交 `.privacy-data/` 下的隐私配置

## 关于 evolve Agent

`security-analysis-evolve` 是平台内置的"自我进化"机制：它会从实战复盘中识别高价值改进，提出 candidate，**与维护者讨论确认后**实施。

外部贡献者不需要走 evolve 流程，直接提 PR 即可。但如果你在分析中发现某个反复踩的坑，可以：
- 提 issue 描述场景和建议（标签 `evolve-candidate`）
- 或者直接按上面的流程提 PR

## 沟通

- **GitHub Issues**：bug 报告、功能请求、技术讨论
- **GitHub Discussions**：使用问题、想法交流、showcase
- **PR 评论**：代码具体讨论

## 致谢

每一位贡献者都会被记录在 [contributors 页面](https://github.com/zylc369/OpenSecurity/graphs/contributors)。重要的知识库贡献会在对应文档末尾标注作者。

---

再次感谢你的贡献！如果有任何问题，随时提 issue 或在 Discussions 发帖。
