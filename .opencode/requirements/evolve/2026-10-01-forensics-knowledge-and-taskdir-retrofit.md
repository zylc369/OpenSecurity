# 2026-10-01 取证知识补齐（VM 镜像链/XKB 识别/材料获取/路由描述）与根会话任务目录补建 — 实施需求

> 状态：已实施（2026-10-01；Phase 3/6 审计通过；as-built 见 §6）
> 来源：SunshineCTF 2026「ghost in the thread (2)」取证任务复盘（2026-10-01 Phase 0/1）。痛点：① 根会话任务目录门控缺陷致 `$TASK_DIR`/`$ROOT_TASK_DIR` 为空、agent 自建目录、续会话断裂；② VM 镜像取证链无记录且 KB 的 7z 指引对 streamOptimized 实测不可行；③ XKB 布局识别技法仅存向量库、MD 无条目；④ 5 个分析 agent 的 description 缺领域覆盖词、路由靠人工翻 KB；⑤ 题面截图→归档→镜像下载链路无记录、gdown 未入依赖清单。
> 关联：`2026-09-29-forensics-toolchain-and-office-macro-knowledge.md`（同取证域，未覆盖本批）；`2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md`（$OPENSECURITY_HOME，与本批任务目录门控无关）
> 决策依据：commit `1de0e97`（2026-10-01 13:41）已把根会话任务目录门控 `INSTRUMENTED_AGENTS`→`SECURITY_AGENTS`（修复 evolve 起点一条腿）；本批补建残留路径（非安全 agent 起步→切换）

## §1 背景与目标

**目标**：① 修正与补齐取证 KB（VM 镜像展开链、XKB 识别、材料获取）；② 扩充 5 分析 agent description 的路由覆盖；③ 补齐依赖/工具清单（gdown / qemu-img）；④ 插件在根会话切换到安全体系 agent 时幂等补建任务目录（复用 flowId + 台账模板），消除 `$TASK_DIR` 空值路径。

**预期收益（四维）**：准确度显著（KB 不再引导死路；路由可命中；台账落点契约恢复）；速度/轮次明显（VM 链免推导、路由免人工翻 KB、材料获取少重试）；上下文微增（KB +约 25 行；prompt 行数 ±0）；插件侧动态注入恢复 2 行 env。

**明确不做**：C4 的 mmls 检测项（随 sleuthkit 配方已覆盖，无独立安装路径）；N1-N5（复盘 Phase 1 已判定不建议做）。

## §2 技术方案

### 2.1 C2a 取证知识补齐 — `disk-memory-forensics.md` §2（替换 OVA/VMDK 行）

目标文本（替换现有 `- **OVA/VMDK**: ...` 一行，原行删除）：

```
- **OVA/VMDK 展开**: OVA=TAR（`tar xf` 得 .ovf+.vmdk）; 展开前先 `qemu-img info disk.vmdk` 判子格式——**streamOptimized**（OVA 导出常见）7z/7zz 打不开（报 `Cannot open the file as [VMDK] archive`），必须 `qemu-img convert -f vmdk -O raw disk.vmdk disk.raw` 转原始镜像; flat/monolithicSparse 可试 `7zz x disk.vmdk` 按路径抽文件（命令名随安装：7z/7zz/7za），split/extent 多文件形态仍走 qemu-img 展开
- **raw 镜像取文件（Sleuth Kit 链）**: `mmls disk.raw` 读分区表（根分区 Start 列，单位=512B 扇区）→ `fls -o <start> -r -p disk.raw > filelist.txt` 全盘列目录+inode → `icat -o <start> disk.raw <inode> > out` 按 inode 提取。**镜像传绝对路径**（相对路径按 CWD 解析，路径不符报 `Error stat(ing) image file`）
```

保留下一行 `- **VMDK/镜像关键文件**: ...`，并在其 Linux 侧补 `/etc`、`/home/*`、`/usr/share`。

### 2.2 C2b XKB 识别 — `disk-memory-forensics.md` §6a（行尾追加一条）

目标文本：

```
- **XKB 键盘布局识别**（VM 镜像问"机器主人用哪个布局"）: 布局文件在 `/usr/share/X11/xkb/symbols/<名字>`。文件名与 `name[Group1]` 可被改成通用名隐藏身份——**不按字母肉眼比对**，把文件与上游公开布局（社区布局仓库的 `Linux/xkb/*`）逐字节 `diff`：变体间常只差 2-3 个键（colstag/rowstag 是若干键位的循环换位），diff 一步定案。辅证：全盘 `grep -a` 布局名命中必须带上下文复核（压缩数据随机字节、`workman` 在 `NetworkManager` 中会假阳性）; 顺带排除其他布局来源（`/etc/conf.d/loadkmap`、`/etc/X11`、`setxkbmap` 痕迹）
```

### 2.3 C2b 通则 + C3 材料获取 + C2a 分诊 — `forensics-methodology.md` §1

① 类型分诊表新增一行（置于"磁盘镜像"行后）：

```
| VM 镜像（`.ova`/`.vmdk`/`.vdi`） | 虚拟机镜像取证 | `disk-memory-forensics.md` §2（qemu-img 展开 + mmls/fls/icat） |
```

② "通用第一步"节追加两条：

```
**素材未本地化（只有平台题面/截图）**：先 websearch 题名+赛事定位官方归档（如 `github.com/sajjadium/ctf-archives` 的 `<赛事>/<年份>/<方向>` 目录）与公开 writeup 中的镜像链接，再下载并 `file` 校验类型（Google Drive 用 `python -m gdown "<id>"` 或 `python -m gdown "https://drive.google.com/uc?id=<id>"`；直链用 `curl`）。大体积先确认总大小再下。
**被改名/伪装的标准 artifact**（配置文件/键盘布局/脚本被改 name 或文件名）：不要肉眼比对，与上游权威原件逐字节 `diff` 定身份（例见 `disk-memory-forensics.md` §6a）。
```

### 2.4 C2a/C2b/C3 索引触发词 — `agents/binary-analysis.md`（行内替换，净 0 行）

- L215 `forensics-methodology.md` 触发条件 → `取证题：拿到 pcap/内存镜像/磁盘镜像/VM 镜像（.ova/.vmdk）/.evtx 日志，或仅有题面截图需先获取素材时`
- L240 `disk-memory-forensics.md` 触发条件 → `磁盘与内存取证（文件系统恢复/RAID/加密容器/VM 镜像展开（OVA/VMDK）/volatility 命令族/勒索处置）`

### 2.5 C2c 路由描述扩充 — 5 个分析 agent 的 frontmatter `description`（行内替换）

| 文件 | 目标 description |
|---|---|
| `agents/binary-analysis.md` | `二进制逆向与 CTF 取证分析（含内存/磁盘/VM 镜像/网络流量/隐写/硬件信号取证、pwn、恶意样本、内网渗透）— 输入目标文件/镜像/流量和分析需求，自动编排工具链完成分析` |
| `agents/crypto-analysis.md` | `密码学分析（RSA/格/ECC/对称与哈希/古典/PRNG 等）— 输入密码学题目（脚本/参数/密文）和分析需求，自动完成密码学攻击与 flag 求解` |
| `agents/web-analysis.md` | `Web 安全分析（SQLi/XSS/SSRF/反序列化/缓存投毒/竞态/客户端攻击等）— 输入 URL/源码目录和分析需求，自动完成审计与利用` |
| `agents/mobile-analysis.md` | `移动应用逆向分析（Android/iOS；脱壳/Frida Hook/协议与加密逆向/加固对抗）— 输入 APK/IPA 和分析需求，自动编排工具链完成分析` |
| `agents/ai-security-analysis.md` | `AI 安全分析（应用层提示注入、RAG/工具调用注入、系统提示词提取 + 模型层越狱攻击）— 输入 LLM 应用 URL/源码/模型名称，自动完成分析` |

规则依据：`opencode-agent-format.md` §"description 是唯一路由层"（单行、无 `|`）。

### 2.6 C4 清单补齐

`control/backend/services/detect_py_deps.py`（`oletools` 条目后 +4 行）：

```python
        PyPkgField(name="gdown", pip_name="gdown", agents=["binary-analysis"],
                   description="Google Drive 公开文件下载（CTF 题面附件/镜像，forensics-methodology）"),
```

`control/backend/services/detect_tools.py`：
- 配方区（`qemu-system-x86_64` 行后）：`PkgToolRecipe(name="qemu-img", pkg_brew="qemu", pkg_linux="qemu-utils"),`
- 检测区（`_auto("qemu-system-x86_64", ...)` 行后）：`_auto("qemu-img", _BIN, "磁盘镜像格式转换/VM 镜像展开（disk-memory-forensics）", ["--version"]),`

### 2.7 C1 插件：根会话任务目录补建

`plugins/lib/session-manager.ts`：

① `SessionData` 新增字段（`justCompacted` 字段附近）：

```ts
  /** 环境信息强制注入请求。补建任务目录后置位——system.transform 读到后强制注入一次并在注入后清空（与 justCompacted 同构）。 */
  envInjectRequested = false;
```

② `upsert` 内 agentName 更新之后（`return session;` 之前）插入一行：

```ts
    this.ensureRootTaskDir(session);
```

③ `createTaskSession` 私有方法之前新增：

```ts
  /**
   * 保证根会话持有任务目录（幂等）。
   * 覆盖路径：会话以非安全体系 agent 起步、同一插件进程内切换到安全体系 agent；
   * 或首消息 createFromAPI 瞬时失败后 taskDir 为空。
   * 已有目录不重建（agent 间切换共用同一任务目录）；非根会话不处理。
   */
  private ensureRootTaskDir(session: SessionData): void {
    if (!session.isRootAgent) return;
    if (!localIsSecurityAgent(session.agentName)) return;
    const existingDir = session.getTaskDir();
    if (existingDir) {
      TaskSessionPersistence.ensureLedgerTemplate(existingDir, session.agentName);
      return;
    }
    const taskSession = this.createTaskSession(
      session.sessionID,
      session.agentName,
      undefined,
      session.flowId,
    );
    const taskDir = taskSession.taskDir ? taskSession.taskDir : null;
    session.setTaskDir(taskDir);
    session.rootTaskDir = taskDir;
    session.envInjectRequested = true;
    debugLog(
      `ensureRootTaskDir: 补建根任务目录 sessionID=${session.sessionID} agent=${session.agentName} taskDir=${taskDir}`,
      session.sessionID,
    );
  }
```

④ `plugins/lib/task-session-persistence.ts` 新增静态方法（供"目录已存在但缺台账模板"复用；evolve 起点目录无模板）：

```ts
  /** 幂等补写分析台账模板（目录已存在但模板缺失时）。仅五分析 agent。 */
  static ensureLedgerTemplate(taskDir: string, agentName: string): void {
    if (!SECURITY_ANALYSIS_AGENTS.includes(agentName)) return;
    const ledgerPath = join(taskDir, cognition.ledgerFilename);
    if (existsSync(ledgerPath)) return;
    writeFileSync(ledgerPath, LEDGER_TEMPLATE);
    debugLog(`ensureLedgerTemplate: 写入分析台账模板 ${ledgerPath}`);
  }
```

`plugins/security-analysis.ts`：
- `shouldInject` 条件追加 `|| session.envInjectRequested`；
- 清理段（`justCompacted` 清理后）追加：

```ts
        if (session.envInjectRequested) {
          session.envInjectRequested = false;
          debugLog(
            `[INFO] system.transform: 清理 envInjectRequested sessionID=${sessionID}`,
            sessionID,
          );
        }
```

### 2.8 架构影响

```
binary-analysis/knowledge-base/{disk-memory-forensics,forensics-methodology}.md ← 文本段落（无依赖变更）
agents/{binary,crypto,web,mobile,ai-security}-analysis.md ← frontmatter description（展开行数不变）
control/backend/services/{detect_py_deps,detect_tools}.py ← 清单追加 → scan/install 链路（既有单向）
plugins/lib/session-manager.ts ← 根会话补建（upsert→ensureRootTaskDir→createTaskSession）→ session.taskDir/rootTaskDir
plugins/lib/task-session-persistence.ts ← ensureLedgerTemplate（幂等补台账模板，复用 LEDGER_TEMPLATE）
plugins/security-analysis.ts ← shouldInject/清理（读 session.envInjectRequested）
```
无新增文件（除测试）、无依赖方向变化、无循环。

## §3 实现规范

### 3.1 实施步骤拆分（每步 ≤200 行）

1. **S1 disk-memory-forensics.md §2 VM 链修正（C2a）** — 文件：`disk-memory-forensics.md` | 1 行拆 2 行（净 +1）；关键文件行行内补 Linux 侧 | 依赖：无 | 验证点：grep 新行存在、旧「7z 直读免挂载」零残留；`qemu-img convert`/`mmls`/`icat -o` 命令在文本中；NUL/控制字节扫描=0；人工读自包含
2. **S2 forensics-methodology.md §1 分诊行+通用第一步两条（C2a/C2b/C3）** — 文件：`forensics-methodology.md` | +3 行 | 依赖：无 | 验证点：grep 三个片段（VM 镜像行 / 素材未本地化 / 被改名）各命中 1；NUL 扫描=0
3. **S3 disk-memory-forensics.md §6a XKB 条目（C2b）** — 文件：`disk-memory-forensics.md` | +1 行 | 依赖：S1（同文件串行）| 验证点：grep `XKB 键盘布局识别` 命中；叙事词 grep（赛事名/Sunshine/ghost）零残留；NUL 扫描=0
4. **S4 binary-analysis.md 索引触发词行内替换（C2a/C2b/C3）** — 文件：`agents/binary-analysis.md` | 2 行内替换（净 0）| 依赖：无 | 验证点：展开行数复算仍 =448（<450）；两行内容含 `VM 镜像`/`仅有题面截图`；无 `|` 结构破坏（表格列数一致）
5. **S5 5 个分析 agent description 扩充（C2c）** — 文件：`agents/{binary,crypto,web,mobile,ai-security}-analysis.md` | 5 行内替换（净 0）| 依赖：无 | 验证点：逐行无 `|`、单行；各 agent 文件行数不变；frontmatter 仍 YAML 合法（yaml.load 通过）
6. **S6 detect_py_deps.py 新增 gdown（C4）** — 文件：`detect_py_deps.py` | +4 行 | 依赖：无 | 验证点：`py_compile` 通过；`scan --json` 含 gdown 且 available=true；`install --dry-run` 含 gdown
7. **S7 detect_tools.py 新增 qemu-img 配方+检测（C4）** — 文件：`detect_tools.py` | +2 行 | 依赖：无 | 验证点：`py_compile` 通过；审计脚本断言配方存在且 `pkg_brew=="qemu"`/`pkg_linux=="qemu-utils"`、`EXTERNAL_TOOLS` 有 qemu-img 检测项、`version_cmd==["--version"]`；scan 该工具 available=true
8. **S8 task-session-persistence.ts：ensureLedgerTemplate（C1）** — 文件：`task-session-persistence.ts` | +11 行 | 依赖：无 | 验证点：`bun build` 零错误；grep 方法存在；`SECURITY_ANALYSIS_AGENTS`/`LEDGER_TEMPLATE`/`cognition.ledgerFilename` 均已在文件内可用
9. **S9 session-manager.ts：字段+ensureRootTaskDir+upsert 钩子（C1）** — 文件：`session-manager.ts` | +30 行 | 依赖：S8 | 验证点：`bun build` 零错误；grep 三处（字段/方法/调用）存在；类型检查无新增错误
10. **S10 security-analysis.ts：shouldInject + 清理（C1）** — 文件：`security-analysis.ts` | +7 行 | 依赖：S9 | 验证点：`bun build` 零错误；grep `envInjectRequested` 3 处（条件/清理/日志）
11. **S11 新增 test-taskdir-retrofit.ts（C1）** — 文件：`plugins/tests/test-taskdir-retrofit.ts`（新建 ~140 行）| 依赖：S8/S9/S10 | 验证点：沙箱运行全绿（T1 build 起步无目录 / T2 切 binary 补建+ledger+映射 / T3 幂等不改路径 / T4 非安全 agent 不建 / T5 安全 agent 首消息直建 / T6 evolve 起点目录无台账→切换补模板）
12. **S12 端到端与回归（C1+C4）** — 文件：无 | 依赖：全部 | 验证点：既有插件测试全绿；`bun build security-analysis.ts` 零错误；nested `opencode run` 冒烟（插件加载 + 环境信息注入 `$TASK_DIR` 正常）；控制台 detect 回归测试子集通过；不可得的验证项在 progress 记录降权

### 3.2 编码规则

- 知识文本零来源叙事（无赛事名/题号/日期/"实测"）；命令示例可执行；行宽不人工折行
- 跨文件引用用 `$AGENT_DIR`/`$SHARED_DIR` 变量形式；不引用 `docs/`
- Python 沿 `PyPkgField`/`PkgToolRecipe`/`_auto` 既有形态，不新增抽象
- 插件状态收在 `SessionData`（规则 9），日志按规则 10 打点
- prompt 改动一律行内替换（binary-analysis 展开 448，余量 1 行）

## §4 验收标准

**功能验收**：S1-S7 文本/清单逐字落盘；qemu-img/gdown 检测可用；S8-S10 补建逻辑在 T1-T5 用例下行为正确（非安全 agent 不建、安全 agent 切换补建、幂等）。
**回归验收**：binary-analysis.md 展开行数=448；5 agent 文件行数不变、frontmatter YAML 合法；既有插件测试与 detect 相关测试全绿；无 `binwalk-full` 式旧名残留。
**架构验收**：改动落位 `knowledge-base/`、`agents/`、`control/backend/services/`、`plugins/lib/`、`plugins/`、`plugins/tests/`、`requirements/evolve/`；零新增运行时文件（测试除外）；无循环依赖。

## §5 与现有需求文档的关系

- 承接 `2026-09-29-forensics-toolchain-and-office-macro-knowledge.md` 未覆盖的 VM 镜像/XKB/材料获取；其 binwalk/oletools/rg 结论不变。
- 与 `2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md` 无交集（该文为 `$OPENSECURITY_HOME`）。
- 修订 `2026-10-01-reflection-idle-exclusion`（commit `1de0e97`）附带的任务目录门控改动：该 commit 已修 evolve 起点，本批补残留切换路径。
- 与 `2026-09-29-analysis-attribution-v2.md` 的"非 instrumented 会话"降级路径不冲突（本批修的是 instrumented 但无任务目录的路径）。

## §6 实施结果

**完成于 2026-10-01**（同日工作会话；S1-S12 全部执行 → 验证通过）。

**as-built（git diff 口径）**：
- `binary-analysis/knowledge-base/disk-memory-forensics.md`：§2 OVA/VMDK 行拆为「OVA/VMDK 展开」+「raw 镜像取文件（Sleuth Kit 链）」两行，关键文件行补 Linux 侧（82→84 行）；§6a 追加 XKB 识别条目。
- `binary-analysis/knowledge-base/forensics-methodology.md`：§1 分诊表 +VM 镜像行；通用第一步 +素材未本地化、+被改名 artifact 两条（239→243 行）。
- `agents/binary-analysis.md`：2 处索引触发词行内替换（净 0）；frontmatter description 扩充。
- `agents/{crypto,web,mobile,ai-security}-analysis.md`：description 扩充（净 0）。
- `control/backend/services/detect_py_deps.py`：+`gdown` 条目。
- `control/backend/services/detect_tools.py`：+`qemu-img` 配方（brew=qemu / linux=qemu-utils）+ 检测项。
- `plugins/lib/session-manager.ts`：`SessionData.envInjectRequested` 字段 + `ensureRootTaskDir` 方法 + `upsert` 调用。
- `plugins/lib/task-session-persistence.ts`：`ensureLedgerTemplate` 静态方法。
- `plugins/security-analysis.ts`：`shouldInject` 追加 `envInjectRequested` + 注入后清理。
- 新增：`plugins/tests/test-taskdir-retrofit.ts`（6 用例）、本需求文档、任务目录 progress.md。

**验证证据**：
- 知识/manifest：S1 新行命中各 1、旧「7z 直读免挂载」全仓 0、NUL/CTRL=0；S2 三片段各 1、表格列一致；S3 命中 1、叙事词 0；S4 expanded 复算 =448、diff 仅 2 行；S5 5 文件 YAML 合法/无 `|`/行数不变；S6 `scan --json` gdown available=True v6.4.0、`install --dry-run` 含 gdown；S7 配方 `pkg_brew=qemu`/`pkg_linux=qemu-utils`、检测项 `version_cmd=["--version"]`、scan available=True v11.1.1。
- 插件：`bun build plugins/security-analysis.ts` 零错误；新测试 6/6（T1-T6）；既有插件测试全绿（reflection-clock 8/8、reflection-config 2/2、permission-timeout 17/17、resume-completion 7/7、test-control 11/11）；控制台 `tests/test_control.py` **97/97**。
- 端到端：nested `opencode run --agent binary-analysis` → 新建任务目录含 ledger.md + logs，环境段注入 `$TASK_DIR`/`$ROOT_TASK_DIR` 实路径；跨进程切换场景（build 起步 → `--session` 切 binary-analysis）实测 `TASK_DIR=/…/20261001_172430_e921_binary-analysis`（非空），映射文件落盘。

**验证边界（如实）**：`qemu-img` 的 Linux 安装分支（apt `qemu-utils`）未实机执行——仓库包事实经 Debian/Ubuntu 官方包页核验（qemu-utils 提供 qemu-img；qemu-system-x86 仅 recommends），mac 检测分支实机通过。C1 的"同进程内 agent 切换"路径由确定性单测覆盖；`opencode run` 为非交互单 agent，无法在单进程内切换 agent，跨进程切换与正常路径已实测。

**审计遗留决策**：`createTaskSession` 内的台账写入块与 `ensureLedgerTemplate` 逻辑相近（2 处，未达规则 2 的 3 次抽象阈值），且 `createTaskSession` 属高风险热路径——保持现状以零行为变更，记录于此。

**修订记录**：Phase 3 审计第 1 轮修正 S1 行数估算与「目录已存在但缺台账模板」遗漏（新增 `ensureLedgerTemplate` 与 T6 用例）。
