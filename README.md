# OpenSecurity

> **中文** | [English](README.en.md)

> AI 驱动的多领域安全分析 Agent 平台 —— 让 LLM 真正像一个研究员团队那样工作。

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## 这是什么

OpenSecurity 让 LLM 端到端地完成一次安全分析：拿到目标文件，自己编排工具链（IDA Pro、Frida、apktool……），一步步推进，最后产出一份可验证的报告。不是问一句答一句，不是停在"我建议你用 IDA 看看"，而是真的把工具跑起来、读输出、做推理、再决定下一步。

覆盖四个安全分析领域 + 一个编排器 + 一个自我进化引擎：

| Agent | 负责什么 |
|-------|---------|
| `security-coordinator` | 复合安全任务拆分 + 分发到专业 Agent |
| `binary-analysis` | 二进制逆向：算法还原、壳检测、漏洞挖掘 |
| `mobile-analysis` | 移动端逆向：APK/IPA 反编译与 Java/Native 分析 |
| `web-analysis` | Web 安全：URL/源码的漏洞审计与攻击链构造 |
| `ai-security-analysis` | AI 应用安全：LLM 应用的提示注入与越狱 |
| `security-analysis-evolve` | 自我进化：从实战复盘中沉淀脚本与知识库 |

## 核心架构

```
.opencode/
├── agents/                  # 6 个 Agent 的主 prompt（LLM 的工作守则）
├── agents-rules/            # 跨 Agent 共享的 prompt 片段（Plugin 自动展开）
├── plugins/
│   └── security-analysis.ts # Plugin：上下文持久化、session 管理、工具拦截
├── binary-analysis/         # 各领域的工具脚本 + 知识库
├── mobile-analysis/
├── web-analysis/
└── ai-security-analysis/
```

**三层分离**：
- **AI 编排层** — Agent prompt（何时调用什么工具、如何推理），由 LLM 执行
- **工具层** — Python/Bash 脚本（query.py、update.py、initial_analysis.py……），工程师维护
- **知识库层** — 按需加载的 Markdown（壳处理策略、Unicorn 模板、Frida 速查……），evolve Agent 持续沉淀

关键决策：**LLM 不直接操作 GUI**。所有 IDA 操作走 `idat -A -S<script>` headless 模式 + IDAPython 脚本，确保分析过程可稳定复现。

## 快速上手

### 前置依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| [OpenCode](https://github.com/anomalyco/opencode) | latest | AI Agent 框架，本平台构建于其上 |
| Python | 3.8+ | 工具脚本运行时（Plugin 自动创建 venv） |
| IDA Pro | 7.6+ | 二进制逆向必需（仅 `binary-analysis` / `mobile-analysis` 需要） |
| C/C++ 编译器 | 任意 | 计算密集型任务用（macOS: clang / Linux: gcc / Windows: VS Build Tools） |

移动端 / Web / AI 安全分析还需对应工具（Frida、apktool、jadx、Playwright……），首次运行时 `detect_env.py` 会自动检测并给出安装指引。

### 安装

```bash
# 1. 克隆仓库（含 submodule，首次推荐）
git clone --recursive https://github.com/zylc369/OpenSecurity.git
cd OpenSecurity

# 已克隆但漏了 submodule？补拉一次：
# git submodule update --init --recursive

# 2. 把 .opencode/ 链接到你的工作目录（或全局配置）
# 方式 A：项目级（推荐，仅对此目录生效）
ln -s "$(pwd)/.opencode" ~/your-workspace/.opencode

# 方式 B：全局级（对所有项目生效）
ln -s "$(pwd)/.opencode" ~/.config/opencode
```

> **关于 submodule**：`vendor/` 下包含 OpenCode、Frida、IDA SDK 等参考源码，方便查阅但不影响运行。磁盘紧张可以不加 `--recursive`，平台核心功能不依赖它们。

### 配置 IDA Pro

IDA Pro 路径通过 `IDA_PRO_HOME` 环境变量指定（IDA Pro 安装目录）。detect_env.py 每次运行检查 `$OPENCODE_ROOT/.ai_env`，文件不存在时创建模板，填入 IDA 安装目录即可：

```ini
# $OPENCODE_ROOT/.ai_env
IDA_PRO_HOME=<IDA Pro 安装目录>
```

也可设置系统环境变量 `IDA_PRO_HOME`（优先级高于 .ai_env）。detect_env.py 自动检测 IDA Pro、编译器、Python 包及外部工具，结果写入 `~/bw-security-analysis/env_cache.json`。

### 第一次分析

```bash
# 在工作目录启动 OpenCode
cd ~/your-workspace
opencode
```

在 TUI 中切换到 `security-coordinator`（复合任务）或具体领域的 Agent（单一任务），然后丢一句话：

```
帮我逆向 /Users/me/Downloads/crackme.exe，找出正确的 license
```

Agent 会自主完成：信息收集 → 分析规划 → 工具执行 → 结果验证 → 报告产出。中间产物持久化在 `~/bw-security-analysis/workspace/<task_id>/` 下，包括反编译输出、截图、求解脚本、最终报告。

## 数据与代码分离

| 类别 | 位置 | 是否提交 git |
|------|------|-------------|
| **代码** | `.opencode/` | ✅ 是 |
| **运行时数据** | `~/bw-security-analysis/` | ❌ 否（venv、config、workspace、logs） |
| **隐私配置** | `.privacy-data/` | ❌ 否（API Key 等） |

## 文档导航

| 文档 | 内容 |
|------|------|
| [项目深度介绍](docs/项目介绍/open-security-介绍.md) | 完整的设计理念、架构详解、反直觉决策 |
| [如何添加新 Agent](docs/contributing/add-new-agent.md) | 扩展平台支持新的安全分析领域 |
| [Roadmap](docs/ROADMAP.md) | 项目路线图与待办方向 |
| [环境搭建详解](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/environment-setup.md) | 各平台工具链安装指南 |
| [Plugin 开发实战](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/knowledge-base/opencode-plugin-development-guide.md) | OpenCode Plugin 工程实践 |
| [IDAPython 编码规范](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/knowledge-base/idapython-conventions.md) | 工具脚本开发规范 |

## 贡献

欢迎各种形式的贡献：新 Agent、新工具脚本、知识库补充、bug 修复、文档改进。

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

特别欢迎的方向（参见 [Roadmap](docs/ROADMAP.md)）：
- IPA 分析路径增强
- AI 安全攻击方法论沉淀
- Windows 内核驱动分析
- 更多框架的 Web 安全知识库

## License

[Apache-2.0](LICENSE)
