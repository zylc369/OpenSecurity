# CTF 工具箱覆盖补全（CtfTools2025 对照审计驱动）

> **实施状态（2026-08-28）**: 即刻批次全部完成并实测验证。实施中的方案修正:
> - flask-unsign / weevely 原计划 pip → flask-unsign 已装（清单 L152 未看见，撤销）; weevely/sstp 不在 pypi（`pip show` 报 from versions: none）→ 改 GitRecipe（sstv 用 pip_pkg 模式）
> - sstv 运行缺 libsndfile → soundfile 升 0.14（自带 bundled 库）修复
> - ilspycmd 首次运行 "must install or update .NET" → net6.0 dll 跨两大版本到 runtime 8 需 wrapper `export DOTNET_ROLL_FORWARD=LatestMajor`（默认 Minor 只允许 6→7）
> - cn-dicts source 路径踩坑: `_opencode_root()` 返回 .opencode 目录本身，source 不带 .opencode/ 前缀
> - **die 撤销**: 三平台发行形态都不干净（linux 无 arm64 资产 / mac arm64 是 .pkg / 官方 deb 拉 Qt 重依赖几百 MB），kali 源无 die 包（build 实测 E: Unable to locate）。查壳能力已有 r2+知识库方案覆盖。如需可后续单独评估（DIE-engine 源码编译或 CLI-only 分发渠道）
> - outguess: kali 源无包（build 实测）→ builder 源码编译（libjpeg-dev + configure/make）→ final COPY
> - 镜像 build 中 apt 失败（Unable to locate）会导致缓存链断裂后 phpggc 段 git not found 的**误导性报错**——排查要看首个 E: 行
> - wrapper 增强: 除 seclists 精确挂载外，参数重写函数 rw_path 把 `$WORDLISTS_DIR` 前缀重写为容器挂载路径（容器内无该环境变量，AI 一套路径心智靠 wrapper 翻译）
>
> **第五十七轮追加（2026-08-29）: Windows shell 前提缺口修复**
> - 缺口: opencode Windows 默认 shell = PowerShell（vendor shell.ts win() 优先级），体系 bash 资产全失效
> - 修复: install.ps1 加 Git Bash 检测（git 上溯 + 常见路径回落，无则阻断 exit 1）+ 项目级 opencode.json 合并写入 shell 键（PS 5.1 兼容）
> - 验证: pwsh 7.4.6 四段实测（语法/失败分支/成功分支 mock/JSON 合并幂等）全过; 待 Windows 真机复验
> - 决策: plugin 不加运行时兜底（安装入口阻断 + 错误自暴露闭合，YAGNI）

## §1 背景与目标

**来源**: 用户提供 108GB 本地 CTF 工具集合（`~/Downloads/ctf教程/CtfTools2025`）做覆盖审计。全量对照（纪律 30 全量法：which / ls bin / pip list 全文）后发现 19 个真缺口 + 1 个架构缺口（字典无统一落点/感知机制）。

**痛点**:
1. 内网综合扫描（fscan）、JWT 全能攻击（jwt_tool）、.NET 反编译（ilspycmd）、Python 3.9+ pyc 反编译（pycdc）等常用能力缺失
2. 隐写三件套缺 outguess/stegsnow/foremost
3. 字典体系只有镜像内 rockyou（51MB）——宿主工具（ffuf/sqlmap）无字典可用、无统一路径约定、AI 无感知通道
4. 审计过程暴露方法论漏洞 2 次（关键词子集证伪、清单有没看见）→ 纪律 30 沉淀

**目标**: 全部缺口按"跨平台自动安装"口径收口——pip 进 venv（detect_py_deps.py）/ 本机单二进制或脚本（detect_tools.py Release/Git/Dotnet/Wordlist Recipe）/ 容器（Dockerfile+DockerRecipe）；字典建立 `$WORDLISTS_DIR` 环境变量心智（注入+描述+知识库全变量化引用）。

## §2 技术方案

### 2.1 三层分配（预研实测后定稿）

| 项 | 落点 | 方式 |
|---|---|---|
| weevely/semgrep/sstv | detect_py_deps.py | PyPkgField（web-analysis/web-analysis/binary-analysis） |
| fscan | detect_tools ReleaseRecipe | repo=shadow1ng/fscan，excl="web,nolocal"（资产名实测：fscan_<ver>_<os>_<arch>，linux_x64 无 amd64 字样） |
| jwt_tool | detect_tools GitRecipe | repo=ticarpi/jwt_tool，entry=jwt_tool.py，req=requirements.txt（无 pypi） |
| yafu | detect_tools ReleaseRecipe | repo=bbuhrow/yafu v3.1.9，仅 linux(avx2)+win 有预编译；mac 无配方 skip（factordb/rsactftool 替代） |
| aleapp/ileapp | detect_tools GitRecipe | req 模式（实施时验证仓库结构） |
| ilspycmd | detect_tools **DotnetRecipe（新类型）** | dotnet-runtime 8.0.11 官方 tarball/zip（三平台直链已验 200）解压 tools/dotnet/ + ilspycmd 8.2.0.7535 nupkg（nuget API 直链已验 GET 可下）解包 tools/net6.0/any → tools/ilspycmd/ + BIN_DIR wrapper `exec dotnet ilspycmd.dll "$@"` |
| seclists | detect_tools **WordlistRecipe（新类型）** | git clone --depth 1 → `~/bw-security-analysis/wordlists/seclists/` |
| rockyou | WordlistRecipe url 模式 | brannondorsey/naive-hashcat release 直链（已验 200，139MB txt） |
| cn 精选字典 | WordlistRecipe source 模式 | git 仓库 `.opencode/wordlists/cn/`（安全设备 2.1M+Top 604K+登入账号 2.1M）复制到 wordlists/cn/ |
| socat/outguess/stegsnow/foremost/aircrack-ng/testdisk/photorec/nikto | Dockerfile v1.1 apt + DockerRecipe | 明天限流重置后 build+push |
| pycdc | Dockerfile v1.1 builder 阶段 cmake 编译 → final COPY | 同上 |
| diec | Dockerfile v1.1 官方 Debian 13 deb（die_3.21_Debian_13_amd64.deb）+ DockerRecipe | mac arm64 只有 .pkg/linux 无 arm64 资产 → 容器统一三平台（后撤销） |
| ffmpeg/ffprobe | UrlRecipe → **DockerRecipe**（实施追加） | mac 无官方静态构建源（evermeet 直链 404 实测），UrlRecipe 仅 linux/win 导致 mac 降级提示 brew——违背跨平台原则; Dockerfile v1.1 apt ffmpeg 三平台统一（rw_path 挂载处理本地文件，实测 8.1.2 可用） |

### 2.2 $WORDLISTS_DIR 心智建设（用户指定）

1. **plugin shell.env 注入**: `output.env.WORDLISTS_DIR = join(homedir(), "bw-security-analysis", "wordlists")`（无条件注入——路径约定恒定，不依赖安装状态）
2. **buildEnvSection 描述**（与 $PYTHON_CMD 同格式）:
   - `$WORDLISTS_DIR`: 字典统一目录，seclists/rockyou.txt/cn 子目录；使用字典一律写 `$WORDLISTS_DIR/xxx`（容器 wrapper 自动挂载到 /usr/share/seclists、/usr/share/wordlists-host）
   - `$PYTHON_CMD/bin`: venv bin 目录（PATH 首位），含 sqlmap/dirsearch/impacket 全家/frida 等 1000+ 可执行命令
3. **知识库全变量化**: wordlists-guide.md 与所有已有字典引用统一 `$WORDLISTS_DIR/xxx` 模式
4. **wrapper 模板增强**: `$WL/seclists → /usr/share/seclists:ro` 精确挂载（容器内与 kali 惯例路径一致）

### 2.3 wordlists-guide.md（$SHARED_DIR/knowledge-base/）

场景→字典→路径速查表（宿主列 `$WORDLISTS_DIR/...`，容器列 `/usr/share/seclists/...`）+ rockyou 双轨说明（宿主 txt + 镜像 gz）+ cn 字典说明。自包含，符合知识编写规范。

## §3 实现规范

**改动范围**:

| 文件 | 改动 |
|---|---|
| detect_py_deps.py | +3 PyPkgField |
| detect_tools.py | +DotnetRecipe/WordlistRecipe 两个 dataclass + 对应 install 分支；+fscan/yafu ReleaseRecipe、+jwt_tool/aleapp/ileapp GitRecipe、+ilspycmd DotnetRecipe、+seclists/rockyou/cn WordlistRecipe；wrapper 模板 +SECL_ARG；EXTERNAL_TOOLS +ToolField |
| .opencode/wordlists/cn/ | 新目录（5MB 精选中文字典） |
| plugins/security-analysis.ts | shell.env +WORDLISTS_DIR；buildEnvSection +2 行描述 |
| binary-analysis/knowledge-base/wordlists-guide.md | 新文件 |
| 知识库已有字典引用 | 统一 $WORDLISTS_DIR 变量化 |
| agent prompt（web/binary） | 知识库索引 +1 行 |
| control/docker/toolbox-{core,full}.Dockerfile | v1.1: apt 9 项 + pycdc cmake + die deb |
| progress.md | 第五十六轮留痕 |

**编码规则**: 强类型（dataclass 字段全注解）、安装幂等（存在即 skip，--force 重装）、单工具失败不中断、wrapper 跨平台（win .cmd 补 .exe 逻辑）。

### §3.1 实施步骤拆分

```
1. detect_py_deps.py +3 pip 项
   - 文件: detect_py_deps.py
   - 预估行数: ~10
   - 验证点: scan --json 含新 3 项；pip install 后 available=true
   - 依赖: 无

2. detect_tools.py DotnetRecipe（类型+安装逻辑+wrapper）
   - 文件: detect_tools.py
   - 预估行数: ~120（runtime 下载解压+nupkg 解包+wrapper 生成+幂等）
   - 验证点: python detect_tools.py install --tool ilspycmd → BIN_DIR/ilspycmd wrapper 可执行 --help
   - 依赖: 无

3. detect_tools.py fscan ReleaseRecipe
   - 文件: detect_tools.py（INSTALLABLE_TOOLS + ToolField）
   - 预估行数: ~8
   - 验证点: install --tool fscan → fscan -v 输出版本
   - 依赖: 无

4. detect_tools.py jwt_tool/yafu/aleapp/ileapp
   - 文件: detect_tools.py
   - 预估行数: ~15
   - 验证点: install --tool jwt_tool → jwt_tool 运行输出（yafu mac 平台 skip 合法）
   - 依赖: 无

5. 中文精选字典复制 .opencode/wordlists/cn/
   - 文件: 新目录
   - 预估行数: 0（cp）
   - 验证点: du ≈5MB；.gitignore 无排除
   - 依赖: 无

6. detect_tools.py WordlistRecipe（类型+安装逻辑+3 配方）
   - 文件: detect_tools.py
   - 预估行数: ~90
   - 验证点: install --tool seclists/rockyou/cn-dicts → wordlists/ 落位（seclists git clone 成功/rockyou.txt 完整/cn 复制）
   - 依赖: 步骤 5

7. detect_tools.py wrapper 模板 SECL_ARG
   - 文件: detect_tools.py（_WRAPPER_TMPL）
   - 预估行数: ~5
   - 验证点: 模板字符串含 SECL_ARG；生成的 wrapper 文本含 /usr/share/seclists 挂载
   - 依赖: 无

8. detect_tools.py EXTERNAL_TOOLS 补 ToolField
   - 文件: detect_tools.py
   - 预估行数: ~12
   - 验证点: scan 输出新条目
   - 依赖: 步骤 2-6

9. plugin shell.env $WORDLISTS_DIR
   - 文件: security-analysis.ts
   - 预估行数: ~6
   - 验证点: node --check；新会话 echo $WORDLISTS_DIR 输出路径
   - 依赖: 无

10. plugin buildEnvSection 2 行描述
   - 文件: security-analysis.ts
   - 预估行数: ~8
   - 验证点: node --check；描述文本含 $WORDLISTS_DIR 与 $PYTHON_CMD/bin
   - 依赖: 步骤 9

11. wordlists-guide.md 编写
   - 文件: $SHARED_DIR/knowledge-base/wordlists-guide.md
   - 预估行数: ~90
   - 验证点: 自包含（读一遍）；全 $WORDLISTS_DIR 模式（grep 死路径=0）
   - 依赖: 步骤 7（路径表与挂载对齐）

12. 知识库已有引用统一变量化
   - 文件: grep 命中的知识库文件
   - 预估行数: ~10
   - 验证点: grep '~/bw-security-analysis/wordlists\|wordlists/seclists' 死路径清零（容器内 /usr/share 路径合法保留）
   - 依赖: 无

13. agent prompt 挂索引 + 瘦身检查
   - 文件: web-analysis.md / binary-analysis.md（或其知识索引段）
   - 预估行数: +2
   - 验证点: 展开行数 < 450；索引指向正确
   - 依赖: 步骤 11

14. Dockerfile v1.1 修改（apt 9 项+pycdc cmake+die deb）+ DockerRecipe 条目 + 本地 build 验证
   - 文件: toolbox-{core,full}.Dockerfile、detect_tools.py DockerRecipe
   - 预估行数: ~40
   - 验证点: 本地 build 成功 + 容器内新工具 --version（push 等限流重置）
   - 依赖: 无（与前面步骤并行）

15. 全量安装验证 + progress.md 留痕
   - 验证点: 全部新工具 --help/--version 实测通过；progress.md 第五十六轮
   - 依赖: 全部
```

## §4 验收标准

**功能验收**:
- [ ] which fscan/jwt_tool/ilspycmd/weevely/semgrep/sstv 命中（yafu 仅 linux/win 宿主，mac skip）
- [ ] `ls $WORDLISTS_DIR/` 含 seclists/rockyou.txt/cn
- [ ] `echo $WORDLISTS_DIR`（新会话）输出 ~/bw-security-analysis/wordlists
- [ ] buildEnvSection 描述含 $WORDLISTS_DIR 与 $PYTHON_CMD/bin
- [ ] wordlists-guide.md 存在且全变量化引用
- [ ] 新 wrapper 含 seclists 精确挂载
- [ ] detect_py_deps scan / detect_tools scan 新条目全绿

**回归验收**:
- [ ] 存量工具 scan 无回归（91 项基线）
- [ ] 存量 pip 依赖 scan 无回归
- [ ] plugin node --check + 现有注入（PYTHON_CMD/PATH）不受影响
- [ ] 镜像 v1.0 tag 不动（v1.1 新推）

**架构验收**:
- [ ] 依赖方向无违反（services 内单向）
- [ ] 新 Recipe 类型注册进 install_recipe 分发 + INSTALLABLE_TOOLS 类型注解更新
- [ ] 知识库无 docs/ 引用、无绝对路径（$WORDLISTS_DIR/$SHARED_DIR 变量）

## §5 与现有需求文档的关系

- 承接 docker-toolbox 体系（镜像 v1.0 已发布）：v1.1 为增量更新，v1.0 tag 永久保留
- 承接 detect_tools 配方家族（Release/Git/Url/Docker/Prebuilt/Node/Dir 7 类）：新增 Dotnet/Wordlist 2 类，注册模式一致
- 纪律 30（全量法验证）为本次审计的方法论产出，已在 progress.md
