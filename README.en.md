# OpenSecurity

> **English** | [中文](README.md)

> AI-driven multi-domain security analysis agent platform — making LLMs work like a real research team.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## What is this

OpenSecurity lets an LLM complete a security analysis end-to-end: take a target file, orchestrate the toolchain (IDA Pro, Frida, apktool...), push forward step by step, and produce a verifiable report. Not Q&A-style chat, not stopping at "I suggest you open it in IDA" — actually running the tools, reading output, reasoning, and deciding the next step.

Covers four security domains + one orchestrator + one self-evolution engine:

| Agent | Responsibility |
|-------|---------------|
| `security-coordinator` | Splits complex tasks and dispatches to domain agents |
| `binary-analysis` | Binary reverse engineering: algorithm recovery, packer detection, vulnerability research |
| `mobile-analysis` | Mobile reverse engineering: APK/IPA decompilation and Java/Native analysis |
| `web-analysis` | Web security: vulnerability auditing and exploit chain construction |
| `ai-security-analysis` | AI application security: prompt injection and jailbreak attacks |
| `security-analysis-evolve` | Self-evolution: distilling reusable scripts and knowledge from real-world analyses |

## Architecture

```
.opencode/
├── agents/                  # 6 Agent prompts (the LLM's "rulebook")
├── agents-rules/            # Shared prompt snippets (auto-expanded by Plugin)
├── plugins/
│   └── security-analysis.ts # Plugin: context persistence, session management, tool interception
├── binary-analysis/         # Per-domain tool scripts + knowledge base
├── mobile-analysis/
├── web-analysis/
└── ai-security-analysis/
```

**Three-layer separation**:
- **AI orchestration layer** — Agent prompts (when to call which tool, how to reason), executed by LLM
- **Tool layer** — Python/Bash scripts (query.py, update.py, initial_analysis.py...), maintained by engineers
- **Knowledge base layer** — On-demand Markdown (packer handling strategies, Unicorn templates, Frida quick reference...), continuously distilled by the evolve agent

Key design decision: **the LLM never operates GUIs directly**. All IDA operations go through `idat -A -S<script>` headless mode + IDAPython scripts, ensuring the analysis process is reproducible.

## Quick Start

### Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| [OpenCode](https://github.com/anomalyco/opencode) | latest | AI agent framework, this platform is built on top of it |
| Python | 3.8+ | Script runtime (Plugin auto-creates venv) |
| IDA Pro | 7.6+ | Required for binary reverse engineering (only `binary-analysis` / `mobile-analysis`) |
| C/C++ compiler | any | For compute-intensive tasks (macOS: clang / Linux: gcc / Windows: VS Build Tools) |

Mobile / Web / AI security analysis also require domain-specific tools (Frida, apktool, jadx, Playwright...). `detect_env.py` auto-detects them on first run and provides installation guidance.

### Installation

```bash
# 1. Clone the repo (with submodules, recommended for first clone)
git clone --recursive https://github.com/zylc369/OpenSecurity.git
cd OpenSecurity

# Already cloned but missed submodules? Pull them:
# git submodule update --init --recursive

# 2. Symlink .opencode/ to your workspace (or global config)
# Option A: project-level (recommended, only affects this directory)
ln -s "$(pwd)/.opencode" ~/your-workspace/.opencode

# Option B: global (affects all projects)
ln -s "$(pwd)/.opencode" ~/.config/opencode
```

> **About submodules**: `vendor/` contains reference source code for OpenCode, Frida, IDA SDK, etc. Useful for browsing but not required to run. If disk space is tight, skip `--recursive` — core functionality doesn't depend on them.

### Configure IDA Pro

IDA Pro path is specified via the `IDA_PRO_HOME` environment variable (IDA Pro install directory). detect_env.py checks `$OPENCODE_ROOT/.ai_env` on each run, creating a template if absent; fill in the IDA install directory:

```ini
# $OPENCODE_ROOT/.ai_env
IDA_PRO_HOME=<IDA Pro install directory>
```

You can also set the system environment variable `IDA_PRO_HOME` (takes precedence over .ai_env). detect_env.py auto-detects IDA Pro, compiler, Python packages, and external tools, writing results to `~/bw-security-analysis/env_cache.json`.

### Your First Analysis

```bash
# Start OpenCode in your workspace
cd ~/your-workspace
opencode
```

Switch to `security-coordinator` (complex tasks) or a domain-specific agent (single-domain tasks) in the TUI, then drop a message:

```
Reverse engineer /Users/me/Downloads/crackme.exe and find the correct license
```

The agent autonomously completes: information gathering → analysis planning → tool execution → result verification → report generation. Intermediate artifacts are persisted under `~/bw-security-analysis/workspace/<task_id>/`, including decompiled output, screenshots, solver scripts, and the final report.

## Data & Code Separation

| Category | Location | Tracked in git |
|----------|----------|---------------|
| **Code** | `.opencode/` | ✅ Yes |
| **Runtime data** | `~/bw-security-analysis/` | ❌ No (venv, config, workspace, logs) |
| **Private config** | `.privacy-data/` | ❌ No (API keys, etc.) |

## Documentation

| Document | Content |
|----------|---------|
| [Project Deep Dive](docs/项目介绍/open-security-介绍.md) | Design philosophy, architecture details, counterintuitive decisions |
| [Adding a New Agent](docs/contributing/add-new-agent.md) | Extending the platform with new security domains |
| [Roadmap](docs/ROADMAP.en.md) | Project roadmap and future directions |
| [Environment Setup](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/environment-setup.md) | Toolchain installation guide per platform |
| [Plugin Development](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/knowledge-base/opencode-plugin-development-guide.md) | OpenCode Plugin engineering practices |
| [IDAPython Conventions](https://github.com/zylc369/OpenSecurity/blob/main/.opencode/binary-analysis/knowledge-base/idapython-conventions.md) | Tool script coding standards |

## Contributing

All forms of contribution are welcome: new agents, new tool scripts, knowledge base additions, bug fixes, documentation improvements.

See [CONTRIBUTING.en.md](CONTRIBUTING.en.md) for details.

Special directions we'd love help with (see [Roadmap](docs/ROADMAP.en.md)):
- IPA analysis enhancement
- AI security attack methodology distillation
- Windows kernel driver analysis
- Web security knowledge base for more frameworks

## License

[Apache-2.0](LICENSE)
