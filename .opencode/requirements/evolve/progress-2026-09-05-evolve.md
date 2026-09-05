# 进化流程进度（2026-09-05 会话）
- Phase 0-1 ✅（复盘+方案确认：A/B/E）
- Phase 2 ✅ 三份需求文档（2026-09-05-{A,B,E}-*.md）
- Phase 3 ✅（3 轮：修复 5 处→复检→纯审计零问题）
- Phase 4 ✅（执行计划+架构图）
- Phase 4.5 ✅（web-analysis.md 展开 384 行 <450）
- Phase 5 进行中：A1✅(llm-perception-verification.md 75行) A2✅(索引+触发规则) B1✅(web-methodology §9, 445→463行) B2✅(无清单记录关闭) E1✅(E1-portable-matrix.md 60工具矩阵)
- 待做：E2(hashcat配方打样)→E3(wrapper路由)→E4(批量迁移)→E5(deps同步)→E6(whisper模型生命周期)→E7(文档同步)→E8(收尾验收)；A/B 的 §4 回归验证（需案例文件路径）
- Phase 6 未开始
## 关键定位信息（下会话直接用）
- detect_tools 安装器：~/.opencode 安装脚本体系（python），装到 ~/bw-security-analysis/bin + tools/
- wrapper 生成器：产出 "# Docker wrapper (auto-generated)" 头的 sh（60个）
- deps 检测后端：控制台 python /api/deps
- whisper 模型现状：~/.cache/whisper 运行时自下载（5个模型 6.8GB）
- brew hashcat 已装(7.1.2, Metal 373.7)——E8 迁移时卸载

## Phase 5 E2 完成（2026-09-05）
- UrlRecipe 扩展: src_names/entries 字段 + SF /download 资产名推断 + tree 分支（_install_url/_install_tree 签名扩展）
- 替换 3 个 DockerRecipe → 便携配方: ffmpeg(osxexperts arm/jvs linux 双架构/gyan win/evermeet x64+Rosetta)、ffprobe(evermeet)、exiftool(SF 官方树+win 单 exe)、ghidra-headless(官方 zip+prereq java，本机未装待验)
- 修复 3 个实现 bug: asset 全平台覆盖误伤、entry 误让 win 走 tree、src_names .exe 全平台生效（_find_file nt 分支本就自动加 .exe）
- 本机实测: exiftool 13.59 ✓ / ffprobe 9.0.1(Rosetta) ✓ / ffmpeg 7.1 arm64 原生 ✓ —— 旧 docker wrapper 已被替换，镜像保留可回滚
- hashcat 按用户指示推迟（win=官方便携/mac=保留 brew/linux=docker 方案已定稿在案）

## Phase 5 E-PM 完成（2026-09-05 包管理器化改造）
按用户定稿方案实施：
1. PM 层: _PM_INSTALL_PREFIX 七种前缀表（含 pacman -S --noconfirm/apk add/zypper 长参差异）+ check_package_manager()（mac 强制 brew/linux 依序检测/失败 sys.exit）
2. INSTALLABLE_TOOLS → installable_tools() 惰性函数 + 模块缓存（修复缺 return 的 bug）
3. ManualItem/ManualCheck（platforms 字段对齐 PyPkgField 命名）+ run_manual_checks（批量 which→一行合并命令报错退出，包名可覆盖）
4. PkgToolRecipe（mac=brew 自动+失败回落 docker / linux=手动清单 / win=docker 回落）+ _remove_stale_wrapper（解决 bin/ 遮蔽系统真身的 17x 性能陷阱）
5. 迁移 35 个 DockerRecipe → PkgToolRecipe（爆破/网络/取证/媒体/逆向/文件系统六族，包名跨 PM 差异显式声明：tshark←wireshark、msfvenom←metasploit、mingw 三名、qemu 拆包等）
6. hashcat win 分支: ReleaseRecipe tree + .7z（py7zr 已在依赖体系）
7. install_all: Phase0（PM检查+手动清单）+ 同名配方去重（hashcat 双配方按平台择一）
真机验证: hashcat skip+清wrapper→which 解析 /opt/homebrew/bin（Metal 373.7 agent PATH 生效）✓；linux 手动分支单测（缺失识别/包名覆盖/一行合并/退出）✓；brew 自动分支 cowsay 端到端 ✓；socat 仅 wrapper 场景正确保留 ✓

## Phase 5 E-PM 二批完成（残留 CLI 工具彻底化）
- GitRecipe 扩展: platforms 门控（phpggc 仅 linux，mac/win 落同名 DockerRecipe）+ setup 脚本（gdb-pwndbg）+ prereq_cmd
- 新 GemRecipe（ruby gem --user-install 免 sudo，递归 glob 定位真实 bin——修复三层路径 bug，lolcat 同名用例端到端验证）+ 新 SrcRecipe（cmake/autotools 源码编译）
- 迁移: nxc→pip(NetExec)、smtp-user-enum→perl GitRecipe、phpggc→linux-only GitRecipe、zsteg/seccomp-tools→GemRecipe、pycdc/pcapfix→SrcRecipe、gdb-pwndbg→git+setup.sh、e2fsck64→e2fsprogs
- linux 手动清单静态前置项: ruby/php/cmake/git/gcc(build-essential)；包名去重保序（sleuthkit×3 修复）
- 服务层红线确认: neo4j-events 由 docker_manager/event_store 管理，与工具层零交集，未触碰
- 最终 docker 残留 4 个（各有正当理由）: marshalsec（无 jar 产物 mvn 过重）、stegseek（.deb 需 root）、qemu-gdb（组合调试需容器保证 qemu/gdb 配对）、boolector（编译链最复杂，保守保留）
- 待办: SrcRecipe 三平台真机构建验证、全量 install_all 真机（需用户授权，会 brew 重型包）、E7 文档同步

## 三残留定案执行（用户拍板）
- marshalsec → 预编译 jar 入库方案 ✓：临时 maven 便携包构建 marshalsec-0.0.3-SNAPSHOT-all.jar(42MB 自包含) → .opencode/tools/ 随仓库；PrebuiltRecipe 扩展 jar/jar_cp 字段（无 Main-Class 的 -cp 模式，首参=主类，对齐上游 README）；真机验证 `marshalsec marshalsec.jndi.LDAPRefServer` 输出 usage ✓ 三平台零构建
- boolector → 用户定案保留 docker（z3 已覆盖主力场景），无代码改动
- qemu-gdb → 定案迁移（重写编排脚本改调系统 qemu/gdb），待执行：读 _QEMU_TMPL 与 docker-toolbox.md §4 语义 → native 版脚本 → 替换配方 → 验证

## 收尾三项（本轮）
1. _install_gem 澄清: 非源码编译（rubygems 预打包）; 源码编译仅剩 pycdc/pcapfix（无产物无 PM 包的最后兜底）
2. marshalsec → Git LFS ✓（.gitattributes 增 tools/*.jar 规则 + jar 已 staged 入 LFS）
3. qemu-gdb → ScriptRecipe 原生编排 ✓（file 判架构+宿主优先匹配修 universal2 fat binary 双切片 bug、gdbstub+remote 语义同容器版、QEMU_SYSROOT 支持动态跨架构）; 同架构路径真机 rc=0 ✓; prereq=file/gdb 缺失给 PM 提示
## 最终 docker 残留: stegseek(Kali源可原生)+boolector(定案保留) — linux 仅 2 个
