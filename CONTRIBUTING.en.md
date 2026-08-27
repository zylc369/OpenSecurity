# Contributing Guide

> **English** | [中文](CONTRIBUTING.md)

Thanks for your interest in OpenSecurity! The core value of this platform lies in **a community-built knowledge base and toolchain** — every security researcher's real-world experience can be distilled into reusable scripts or documents, making the platform stronger over time.

## Types of Contributions

| Type | Difficulty | Examples |
|------|-----------|----------|
| 🐛 Bug fix | Low | Fix script crashes, prompt logic errors |
| 📚 Documentation | Low | Fix descriptions, add examples, translations |
| 🔧 Knowledge base | Medium | Add vulnerability patterns, packer handling strategies, algorithm identification tips |
| 🛠️ Tool scripts | Medium | Add IDAPython scripts, Frida hook templates |
| 🤖 New Agent | High | Extend to a new security domain (see [Adding a New Agent Guide](docs/contributing/add-new-agent.md)) |
| 🎯 Platform mechanism | High | Plugin hook enhancement, context management optimization |

## Code of Conduct

- **Be respectful**: Technical discussions focus on the issue, not the person. No personal attacks.
- **Be patient and clear**: Be friendly to new contributors. Search existing issues before asking.
- **Evidence first**: Technical conclusions require verifiable evidence (IDA output, tool results, source references). No gut-feeling claims.
- **Safety red line**: Do not submit real exploit details for undisclosed vulnerabilities (during CVE embargo) in PRs. Do not submit tools designed for direct misuse.

## Development Setup

```bash
# 1. Fork the repo, then clone
git clone https://github.com/<your-username>/OpenSecurity.git
cd OpenSecurity

# 2. Add upstream
git remote add upstream https://github.com/zylc369/OpenSecurity.git

# 3. Install dev dependencies (OpenCode Plugin SDK + test tools)
cd .opencode && bun install && cd ..
python -m pip install pytest

# 4. Symlink to your workspace for testing
ln -s "$(pwd)/.opencode" ~/your-workspace/.opencode

# 5. Verify Plugin is loaded
# Start opencode, enter any agent session, confirm the top of system prompt shows:
# [系统完整性] Plugin 已加载。当前 Agent: ...
```

See [README Quick Start](README.en.md#quick-start) for details.

## Contribution Workflow

### 1. Find a task

- Browse issues labeled [`good first issue`](https://github.com/zylc369/OpenSecurity/labels/good%20first%20issue) (great for first contributions)
- Browse issues labeled [`help wanted`](https://github.com/zylc369/OpenSecurity/labels/help%20wanted)
- Read the [Roadmap](docs/ROADMAP.en.md) for directions you're interested in
- You can also file an issue if you find a bug or improvement yourself

### 2. Develop

```bash
# Create a branch from main (see naming conventions below)
git checkout -b feat/add-rust-analysis-agent
# or
git checkout -b fix/query-py-thunk-crash

# Develop...

# Local testing
cd test && python -m pytest test_opencode.py
```

### 3. Commit

```bash
git add <relevant files>
git commit -m "<type>: <brief description>"
```

#### Commit Message Convention

Format: `<type>: <description>`

| type | Purpose | Example |
|------|---------|---------|
| `feat` | New feature | `feat: add Rust binary analysis agent` |
| `fix` | Bug fix | `fix: query.py crash on thunk resolution` |
| `docs` | Documentation | `docs: add Frida 17.x migration guide` |
| `refactor` | Refactor (no behavior change) | `refactor: extract JSON output logic from _base.py` |
| `perf` | Performance | `perf: parallelize string scanning in initial_analysis.py` |
| `test` | Tests | `test: add unit tests for update.py rename` |
| `chore` | Misc | `chore: bump @opencode-ai/plugin to 1.5.0` |

#### Branch Naming

- Feature: `feat/<short-desc>`, e.g. `feat/rust-agent`
- Fix: `fix/<short-desc>`, e.g. `fix/thunk-crash`
- Docs: `docs/<short-desc>`, e.g. `docs/ipa-tutorial`

### 4. Open a PR

```bash
git push origin feat/add-rust-analysis-agent
# Open a PR on GitHub, targeting the main branch
```

The PR template will guide you to fill in:
- What changed and why
- How to test
- Whether existing functionality is affected

## Code Standards

### Python (tool scripts)

Follows the IDAPython conventions from `binary-analysis/`:

- Use `from _base import run_headless, log, ...` to import common modules
- Headless entry point at module level (not inside `if __name__`)
- **Forbidden**: `import idc`, `import idaapi`, `from ida_xxx import yyy` (use `_base` wrapper instead)
- Use double quotes for strings
- Logs in Chinese with `[*]`/`[+]`/`[!]` prefixes
- Must call `auto_wait()` and `qexit()` (handled automatically by `run_headless`)

Full conventions: [`.opencode/binary-analysis/knowledge-base/idapython-conventions.md`](.opencode/binary-analysis/knowledge-base/idapython-conventions.md).

### TypeScript (Plugin)

- Strict typing (avoid `any`, annotate explicitly when needed)
- Error handling: all external calls (fs, execSync, API) must be wrapped in try-catch
- Logging: use `debugLog()`, no direct `console.log`
- File paths: use `join()` instead of string concatenation

### Markdown (Agent prompts / knowledge base)

- Primarily Chinese (consistent with existing docs)
- Use `{{buwai-rule:snippet-name}}` to reference shared snippets, avoid duplication
- Tables over long paragraphs
- Command examples must be copy-pasteable (use variables or absolute paths)
- Knowledge base docs follow "on-demand loading": one file per topic, no kitchen-sink docs

### Agent prompts (`.opencode/agents/*.md`)

When modifying agent prompts:
- Frontmatter fields must be complete (`description`, `mode`, `buwai-extension-id`, `permission`)
- Use `agents-rules/` for shared rules, edit `.md` for agent-specific logic
- Any change must be tested with a full analysis run to ensure existing behavior isn't broken

## Project Structure Cheat Sheet

| What to change | Where |
|----------------|-------|
| Agent work logic | `.opencode/agents/<name>.md` |
| Shared rules across agents | `.opencode/agents-rules/<rule>.md` |
| Plugin behavior (hooks, injection) | `.opencode/plugins/security-analysis.ts` |
| Binary tool scripts | `.opencode/binary-analysis/` (includes `_base.py` etc.) |
| Mobile tools/knowledge | `.opencode/mobile-analysis/` |
| Web tools/knowledge | `.opencode/web-analysis/` |
| AI security tools/knowledge | `.opencode/ai-security-analysis/` |
| User docs | `docs/` |
| Tests | `test/` |

## Adding a Tool Script

1. **Classify**: Is it an IDAPython script (via idat) or a standalone Python script?
2. **Reuse base layer**: Import from `_base.py` — `run_headless`, `log`, `JSONEncoder`, etc.
3. **Pass args via env vars**: Don't use `sys.argv`. Use `IDA_*` environment variables (see `query.py`)
4. **JSON output**: Write all results to the path specified by `IDA_OUTPUT`, don't print to stdout
5. **Document**: Describe the call signature and parameters in the corresponding agent's knowledge base or main prompt
6. **Test**: Run a full analysis with a real sample

## Adding a Knowledge Base Document

1. **Scope**: One file per topic (e.g. "VMProtect Handling Strategy"), no omnibus docs
2. **Location**: Place under the corresponding agent's `knowledge-base/`
3. **Format**: Reference existing docs (heading levels, tables, command examples)
4. **Trigger condition**: Register in the agent's main prompt "Knowledge Base Index" table
5. **On-demand loading**: Don't force-load at agent startup; let the agent decide based on context

## PR Review Criteria

Reviewers will check:

- [ ] Code follows the standards above
- [ ] New features have corresponding docs or prompt updates
- [ ] Existing agent workflows aren't broken (key: test once)
- [ ] Commit message follows convention
- [ ] No runtime data from `~/bw-security-analysis/` committed
- [ ] No private config from `.privacy-data/` committed

## About the evolve Agent

`security-analysis-evolve` is the platform's built-in "self-evolution" mechanism: it identifies high-value improvements from real-world analyses, proposes candidates, and implements them **after discussion and confirmation with maintainers**.

External contributors don't need to go through the evolve pipeline — just open a PR directly. But if you notice a recurring pitfall during analysis, you can:
- File an issue describing the scenario and suggestion (label `evolve-candidate`)
- Or directly open a PR following the workflow above

## Communication

- **GitHub Issues**: Bug reports, feature requests, technical discussions
- **GitHub Discussions**: Usage questions, idea exchange, showcases
- **PR comments**: Code-specific discussions

## Acknowledgments

Every contributor is recorded on the [contributors page](https://github.com/zylc369/OpenSecurity/graphs/contributors). Significant knowledge base contributions are credited at the end of the corresponding document.

---

Thanks again for contributing! If you have any questions, feel free to file an issue or post in Discussions.
