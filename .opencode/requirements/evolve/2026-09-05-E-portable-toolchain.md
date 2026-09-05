# 需求E：工具链三平台便携化 + 智能路由 + 模型生命周期
## §1 背景与目标
来源：同上复盘 + 用户决策（三条确认：推荐做执行；hashcat 三平台便携版；docker 全替换为便携版——经可行性审计后保留三级回落）。痛点：wrapper 遮蔽原生版致 17 倍 GPU 差距被静默吃掉；挂载不可见；stdout 截断；手动超时；whisper 3GB 静默下载。目标：用户/AI 零知识，盲敲命令即最优路径。设计全文见任务目录 EVOLVE_DESIGN_E.md。
## §2 技术方案
- E1 安装层：改现有 detect_tools/install 脚本（Python）工具配方——官方便携包下载+SHA256+架构判别（复用 node/adb 既有机制），落点 tools/，规则文件入 $WORDLISTS_DIR/rules/。原位进化，不新增散装脚本。
- E2 可行性矩阵：逐工具审计三平台便携版可得性（stegseek 仅 Linux、nmap Win 需驱动等），产出"便携→docker→报错"三级回落表；迁移含卸载 brew hashcat。
- E3 wrapper 路由化：现有 sh wrapper 改造——原生便携二进制存在且可执行→直接 exec（参数/stdout 透传）；docker 分支：挂载扩至整个 DATA_DIR、WRAPPER_TIMEOUT_DEFAULT 环境变量兜底、输出 tee 至 $TASK_DIR/logs/<tool>-<ts>.log 并回显路径；tshark 过滤器改临时文件传递（与 §4 回归条款一致：tshark 为本期范围，其余工具 wrapper 行为不劣化）。
- E4 检测同步：先定位 /api/deps 后端检测脚本实际位置（控制台 Python 代码内），再将其判定目标改为便携二进制存在+可执行，与安装布局同源。
- E5 模型生命周期：whisper 模型纳入现有 GLM-OCR 式"预置→按需→空闲卸载"机制（复用既有代码，Phase 3 审计时先定位该代码现状）。
- E6 文档同步（明确文件清单）：①security-analysis.ts buildEnvSection 中"容器 wrapper 自动挂载"描述段；②agents/web-analysis.md 等提及 docker wrapper 的 prompt 文案；③wordlists-guide.md 等知识库中 wrapper 行为描述。全部改为"便携优先+docker 回落"表述。
## §3 实现规范
### §3.1 步骤（每步 ≤200 行，含验证点）
1. E2 矩阵审计（纯调研，产出回落表文件）。验证：表覆盖 bin/ 下全部 wrapper 工具。
2. E1 hashcat 配方改造（单工具打样）。验证：干净环境 install.sh 后 tools/ 出现便携 hashcat，SHA256 校验日志存在。
3. E3 wrapper 路由改造（基于打样验证路由/回落）。验证：盲敲 hashcat -I 显示 Metal；删便携版后回落 docker。
4. E1 其余工具配方批量迁移（按矩阵表逐工具，每工具一提交粒度）。验证：矩阵表内工具全部按预期路径执行。
5. E4 检测脚本同步。验证：删便携二进制后 deps 报缺失，装回报就绪。
6. E5 whisper 模型接入既有生命周期机制。验证：模型按需加载、空闲卸载、无运行时静默下载。
7. E6 文档/prompt 同步。验证：grep 无过时 docker 描述残留。
8. 迁移收尾：brew 卸载指引+全平台验收脚本。验证：§4 全过。
## §4 验收标准
功能：全新 macOS 一条 install.sh → 盲敲 hashcat 走便携+Metal；无网/无便携回落 docker；规则全平台可见；whisper 无静默下载。回归：tshark/ffmpeg 等既有 wrapper 行为不劣化（相对路径/过滤器放宽为增强项）。架构：全部改动位于 ~/bw-security-analysis 安装器 + .opencode wrapper 层，遵守单向依赖。
## §5 关系
EVOLVE_DESIGN_E.md 为设计源；依赖项 A/B 无代码耦合可并行；E5 依赖既有模型管理代码（Phase 3 定位）。
