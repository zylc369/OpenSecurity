# 需求: 外部工具自动安装（detect_tools.py 升级 + install.sh 串联 + PATH 注入）

## §1 背景与目标

来源: 第 12-14 轮工具治理把 tool-dependency-index.md 收敛为"需手动安装清单"。经三平台资产实测，其中约 35 个工具可通过 GitHub Releases / git clone / pip git+ **免密、跨平台（win/mac/linux）自动安装**。

目标: 这批工具安装升级 `detect_tools.py`（像 detect_py_deps.py 一样 CLI + import 双模式）；`install.sh` 在 pip 依赖后串联调用；安装到 `~/bw-security-analysis/bin`，由插件注入 PATH。

收益: 换机一键获得全量工具链（此前手动清单 59 行 → 自动 ~35 项）。

## §2 技术方案

### 2.1 detect_tools.py 新增安装能力

新增安装清单（强类型 dataclass）:
```
ReleaseRecipe:  repo, asset_match: dict[平台键→关键词list], kind(binary|archive|jar), bins(产物清单), prereq(java?)
GitRecipe:      repo, wrapper_target(入口脚本相对路径), py_run(用哪个解释器跑)
PipGitRecipe:   url(git+https://...)
平台键: darwin-arm64 / darwin-amd64 / linux-arm64 / linux-amd64 / win-amd64
```
ToolsInstaller 类: `install_all(progress_cb) / install_tool(name) / list_installable()`:
- 幂等: `which(tool)` 命中（brew 等已装）或 `BIN_DIR/<产物>` 存在 → 跳过; `--force` 重装
- 下载: urllib.request（纯标准库，无外部依赖）; GitHub API `releases/latest` 拿资产
- 解压: tarfile（tar.gz/xz）/ zipfile（zip）; 单二进制重命名+chmod; 归档内指定 bins 提取到 BIN_DIR
- wrapper: jar 类生成 `bin/<name>`（sh: `exec java -jar $TOOLS_SRC/<name>/*.jar "$@"`; win 生成 .cmd）; git python 类生成 `bin/<name>`（`exec $PYTHON_CMD_TOOLS <clone>/entry.py "$@"`）
- git clone: `--depth 1` 到 `~/bw-security-analysis/tools/<name>/`
- pip git+: 用 venv python（复用 py_deps 的 VENV_DIR 常量推导）执行
- 前置检查: java 类工具无 java → 跳过并告警; 网络失败 → 单工具告警不中断（可选层语义）
- 失败语义: install 子命令单个工具失败返回非零?——否，工具是可选增强，失败告警继续，最终 summary 列出成败（--strict 严格模式保留给未来）

CLI 扩展: `install [--tool X] [--force] [--dry-run]` / `list-installable`（既有 scan 不变）。

### 2.2 EXTERNAL_TOOLS 增补 + resolve_tool_path 扩展

- 新增工具进 EXTERNAL_TOOLS（required=False, agents 归属, version_cmd 关键项才填）→ 控制台 scan 自然展示
- `resolve_tool_path`: which 未命中时回落查 `BIN_DIR/<name>`(.exe) —— 后端进程无插件注入的 PATH，必须显式回落才能在控制台看到 bin 安装的工具

### 2.3 install.sh 链式串联

`exec` 改为普通调用: py_deps install（失败 exit 1）→ 成功后 `"$PYTHON" detect_tools.py install`（工具层失败不中断安装脚本，脚本退出码只由 pip 层决定）。

### 2.4 插件 PATH 注入

security-analysis.ts shell.env: PATH 数组 `[venvBin, join(homedir(),"bw-security-analysis","bin"), PATH]`（filter(Boolean) 防空）。

### 2.5 tool-dependency-index.md 分区

重排为两节: 「✅ 自动安装（install.sh 一键）」 / 「仍需手动」——手动节保留原"无法替代原因+环境要求"。

### 2.6 安装范围定案（默认，用户可否决）

- **自动**: nuclei/dalfox/ffuf/gobuster/gau/feroxbuster/subfinder/httpx/katana/naabu/dnsx/tlsx/chisel/ligolo-ng/frp/bkcrack/upx/wabt（releases 二进制）; ysoserial/apktool/jadx（java）; NetExec/RsaCtfTool/wesng/windapsearch/reGeorg/redis-rogue-server/pyinstxtractor/Pyarmor-1shot/searchsploit(exploitdb depth1)/ccupp/ajpShooter（git/pip-git）; ffmpeg+ffprobe（三平台静态构建源）
- **手动保留**: Ghidra（400MB 按需）/JsRpc（npm）/sox/exiftool/smtp-user-enum（perl 或非标源）/bftools（非 GitHub 源，内联已覆盖）/hashcat/john/nmap/hydra/kali 套件/steghide 族/de4dot/pycdc/radare2/gdb/qemu/mingw/SleuthKit/WinDbg 等编译或系统层依赖项/xray（release 通道异常待实测，若资产匹配失败回落手动）
- gaps: repo 归属待实测确认，不确定则保持手动

## §3 实现规范

改动文件: detect_tools.py（核心，+~400 行拆 3 步）/ install.sh（~6 行）/ security-analysis.ts（~4 行）/ tool-dependency-index.md（重排）。
编码规则: 强类型 dataclass; 禁裸 dict 传业务数据; 每个跳过/失败分支打日志; 路径跨平台（os.path.join / ntpath 感知 .exe/.cmd）。

### §3.1 实施步骤

1. **manifest 数据结构 + 安装清单定义**（detect_tools.py, ~150 行）
   - 验证: `compile` 语法过 + `list-installable`（步骤 3 一起验则先以 `python -c "import..."` 验 import）
2. **ToolsInstaller 核心**（下载/解压/wrapper/幂等/java 检查, ~180 行）
   - 验证: 单装 `nuclei` → `~/bw-security-analysis/bin/nuclei -version` 输出版本
3. **CLI 子命令 + EXTERNAL_TOOLS 增补 + resolve_tool_path 回落 BIN_DIR**（~80 行）
   - 验证: `detect_tools.py list-installable` 列表正确; `scan --json` 含新工具且已装的 available=true
4. **install.sh 串联**（~6 行）
   - 验证: `bash install.sh`（dry-run 模式行为 + 实际链式执行日志）
5. **插件 PATH 注入**（security-analysis.ts ~4 行）
   - 验证: `node --check` + 新 bash 会话模拟（读注入逻辑+debugLog）
6. **全量安装实测 + 失败项回落**
   - 验证: `detect_tools.py install` 全跑; 每个产物 `--version`/`-h` 抽验; 失败项（如 xray/gaps 资产不匹配）改回手动清单
7. **tool-dependency-index.md 重排**（两分类）
   - 验证: 逐行核对自动节与实际安装成功清单一致
8. **progress.md 留痕**

## §4 验收标准

- 功能: 新机 `bash .opencode/install.sh` 一键后，自动清单内工具在 agent 会话中 PATH 直接可用（nuclei/ffuf/bkcrack/jadx/ysoserial/nxc 等）; 重跑幂等跳过; `--force` 重装; 控制台 deps 页可见新工具状态
- 回归: detect_tools 既有 scan 行为不变（idapro/apktool/jadx/adb 等原有条目不受影响）; routes/deps.py、routes/install.py 零改动仍工作; 插件现有注入（PYTHON_CMD/IDAT/TASK_DIR 等）不受影响; detect_py_deps install 不变
- 架构: 依赖方向不变（detect_tools 不 import detect_py_deps——VENV 路径用同值常量本地定义避免服务间耦合）; 全 dataclass 强类型; install.sh 只做启动器

## §5 与现有需求文档的关系

承接第 12-14 轮工具治理（progress.md）：知识库去外部工具化后，把"必须手动"的清单最小化——本需求是收官动作。
